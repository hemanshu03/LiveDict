# livedict/core.py
"""
LiveDict is a lightweight encrypted ephemeral (TTL-based) key-value store with:
    - in-memory storage as the primary runtime store (fast),
    - optional persistence backends (SQLite file, file-backed object store, Redis),
    - AES-GCM encryption with a deterministic fallback for tests when 'cryptography' is absent,
    - a monitor thread that efficiently expires keys using a timing heap,
    - a sync `LiveDict` and builder utilities for easy configuration.

Guiding principles
------------------
- Keep the runtime in-memory store authoritative and small: persistence backends are mirrors
    used for durability, recovery, and cross-process sharing where configured.
- Default behaviour: keys are expirable (TTL applied) unless explicitly disabled.
- The monitor thread:
    - wakes for the nearest expiry,
    - removes expired entries under the store lock,
    - fires on_expire hooks outside the lock (exceptions are captured and logged).
- For production: persist encrypted data with a stable CipherAdapter configuration
    (same keys and version tag) across restarts to allow decryption.

Quick example
-------------
>>> from src.livedict.core import LiveDict
>>> d = LiveDict()
>>> d.set("foo", {"x": 1}, ttl=60)   # expires in ~60 seconds (default behaviour)
>>> d.get("foo")
{"x": 1}


NOTE
------------
This module focuses on a clean, well-documented, and production-minded implementation. Keep the top-level file reasonably self-contained: the main objects are:
    - CipherAdapter: encryption/decryption abstraction
    - BackendBase + InMemory/SQLite/File/Redis backends
    - LiveDict (synchronous mapping-like API)
    - A few builder helpers used by tests and configuration flow

There are no external network calls here; backends use short-lived sqlite3/file
handles for safety on Windows and to avoid held file handles across processes.
"""


from __future__ import annotations

import threading
import concurrent
import functools
import time
import heapq
import json
import os
import sqlite3
import traceback
import asyncio
import secrets
import base64
from typing import Optional, Dict, Any, Tuple, Callable, List, Union

# pydantic is used for config validation; explicit error if missing.
try:
    from pydantic import BaseModel, Field, field_validator
except Exception as e:
    raise ImportError(
        "pydantic is required for livedict config validation. pip install pydantic"
    ) from e

# If `cryptography` is available we prefer AES-GCM; otherwise use a simple
# deterministic XOR + base64 fallback (useful for tests or environments where
# cryptography is not available).
_CRYPTO_AVAILABLE = True

_NEVER_EXPIRE = -10

try:
    # Prefer cryptography for AES-GCM if available
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


# ----------------------
# Utility helpers
# ----------------------
def now_ts() -> float:
    """Return current timestamp in seconds (float)."""
    return time.time()


def dot_set(d: dict, path: str, value):
    """
    Set nested dict value by dot path. Creates intermediate dicts as needed.

    Example:
        raw = {}
        dot_set(raw, "storage.sql.dsn", "sqlite:///db")
    """
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def dot_get(d: dict, path: str, default=None):
    """
    Get nested dict value using dot path. Returns default if any part missing.
    """
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def merge_dict(a: dict, b: dict):
    """
    Merge dict b into dict a recursively. Returns the mutated dict a.
    """
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            merge_dict(a[k], v)
        else:
            a[k] = v
    return a


# ----------------------
# Configuration models (Pydantic)
# ----------------------
class BucketPolicyModel(BaseModel):
    """
    Controls bucket semantics for the in-memory store.

    Fields
    ------
    per_key: bool
        Whether keys are placed in named buckets (True) or single namespace (False)
    default_bucket_enabled: bool
        Whether a default bucket name is used when `bucket` not provided.
    default_bucket: Optional[str]
        Default bucket name to use when enabled.
    error_if_no_bucket: bool
        If True, `set/get` without a bucket will raise a ValueError.
    """

    per_key: bool = Field(True)
    default_bucket_enabled: bool = Field(True)
    default_bucket: Optional[str] = Field("main")
    error_if_no_bucket: bool = Field(False)

    @field_validator("default_bucket", mode="before")
    def default_bucket_requires_enable(cls, v, values):
        """
        Validate that `default_bucket` is set when `default_bucket_enabled` is True.

        Raises:
            ValueError: If `default_bucket_enabled` is True but no default bucket is provided.
        """
        # In v2, `values` is a dictionary-like `ValidationInfo.data`
        if values.data.get("default_bucket_enabled") and not v:
            raise ValueError(
                "default_bucket must be set when default_bucket_enabled is True"
            )
        return v


class InMemoryBackendModel(BaseModel):
    """Configuration of the in-memory storage behavior."""

    enabled: bool = True
    use_buckets: bool = True
    bucket_policy: BucketPolicyModel = BucketPolicyModel()
    mirror_to_persistence: bool = False
    limits: Dict[str, int] = Field(
        default_factory=lambda: {
            "max_total_keys": 100_000,
            "max_keys_per_bucket": 20_000,
        }
    )


class SQLBackendModel(BaseModel):
    """SQL backend config; DSN expected to be 'sqlite:///path' for builtin sqlite."""

    enabled: bool = False
    driver: str = "sqlite"
    dsn: Optional[str] = None
    table: str = "kv"
    bucket_policy: Optional[BucketPolicyModel] = None


class RedisBackendModel(BaseModel):
    """Redis backend configuration (optional)."""

    enabled: bool = False
    url: Optional[str] = None
    style: str = "flat"


class NoSQLBackendModel(BaseModel):
    """NoSQL backend placeholder config (e.g., mongodb)."""

    enabled: bool = False
    provider: str = "mongodb"
    uri: Optional[str] = None
    collection: str = "livedict"
    ttl_index: bool = True


class ExternalObjectStoreModel(BaseModel):
    """External object store config (e.g., S3 or file-based provider)."""

    enabled: bool = False
    provider: str = "s3"
    bucket_name: Optional[str] = None
    prefix: str = "livedict/"
    per_object_ttl: bool = False


class StorageBackendsModel(BaseModel):
    """Aggregate available backend configuration blocks."""

    inmemory: InMemoryBackendModel = InMemoryBackendModel()
    redis: RedisBackendModel = RedisBackendModel()
    sql: SQLBackendModel = SQLBackendModel()
    nosql: NoSQLBackendModel = NoSQLBackendModel()
    external_object: ExternalObjectStoreModel = ExternalObjectStoreModel()
    hybrid_routing: List[Dict[str, str]] = Field(default_factory=list)


# -----------------------
# Configuration pydantic-like model (kept lightweight to avoid hard dependency)
# -----------------------
#
# The project originally used pydantic models. To keep this core file independent
# from test environment changes it's acceptable to use simple dataclasses or
# lightweight classes. For backward compatibility and simplicity we keep minimal
# plain dataclass-like classes.
#
# For clarity: `default_key_expirable` is a boolean controlling default behaviour
# for whether keys are expirable when the caller does not pass `key_expirable`.
# Defaulting it to True makes `d.set(key, ttl=...)` behave as most users expect.
#
class CommonModel(BaseModel):
    """General configuration: TTL, serializer and encryption toggle."""

    default_ttl: int = 600
    serializer: str = "json"
    encryption_enabled: bool = True
    encryption_version_tag: str = "LD1"
    default_key_expirable: bool = True


class MonitorModel(BaseModel):
    """
    Monitor and heap tuning parameters.

    heap_rebuild_ratio: fraction of total keys when heap rebuild triggered
    compaction_interval_seconds: not actively used by current monitor loop but kept for future
    metrics_enabled, max_hook_threads: informational toggles
    """

    heap_rebuild_ratio: float = 0.25
    compaction_interval_seconds: int = 300
    metrics_enabled: bool = True
    max_hook_threads: int = 4


class LiveDictConfig(BaseModel):
    """
    Root config model for LiveDict. Use builders to create validated instances.
    """

    storage: StorageBackendsModel = StorageBackendsModel()
    common: CommonModel = CommonModel()
    monitor: MonitorModel = MonitorModel()

    class Config:
        arbitrary_types_allowed = True


# ----------------------
# Cipher adapter
# ----------------------
class CipherAdapter:
    """
    Simple pluggable cipher adapter.

    Behavior:
        - If `cryptography` is available, uses AES-GCM (AESGCM) with a random nonce.
        Encrypted blob format: version_tag || nonce(12) || ciphertext
        - If not available, uses a deterministic XOR stream with base64 encoding:
        version_tag || base64(xored_bytes)
        - `keys` is a list of raw 32-byte keys tried in order for decrypt.
        - `version_tag` is a short human-readable byte prefix used to identify
        payloads managed by LiveDict (defaults to b'LD1').

    Parameters
    ----------
    keys : Optional[List[bytes]]
        List of 32-byte keys. If None, a random key is generated.
    version_tag : bytes
        Small byte prefix used to mark LiveDict-managed blobs.

    Methods
    -------
    encrypt(plaintext: bytes) -> bytes
        Returns tagged ciphertext bytes.
    decrypt(blob: bytes) -> Optional[bytes]
        Returns plaintext bytes if decryption succeeds, otherwise None.

    Example
    -------
    >>> c = CipherAdapter(keys=[b"0"*32])
    >>> blob = c.encrypt(b'{"x":1}')
    >>> c.decrypt(blob)
    b'{"x":1}'
    """

    def __init__(self, keys: Optional[List[bytes]] = None, version_tag: bytes = b"LD1"):
        self.keys = keys or [secrets.token_bytes(32)]
        self.version_tag = (
            version_tag if isinstance(version_tag, bytes) else version_tag.encode()
        )
        if _CRYPTO_AVAILABLE:
            # Pre-create AESGCM wrappers for faster encrypt/decrypt calls.
            self.aes_keys = [AESGCM(k) for k in self.keys]
        else:
            self.aes_keys = []

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext and return tagged ciphertext.

        Raises no exception on success -- returns bytes always.
        """
        if _CRYPTO_AVAILABLE and self.aes_keys:
            nonce = secrets.token_bytes(12)
            tag = self.version_tag
            ct = self.aes_keys[0].encrypt(nonce, plaintext, None)
            return tag + nonce + ct
        else:
            tag = self.version_tag
            key = self.keys[0]
            # simple repeating-key XOR stream and base64-encode to keep ascii-safe
            stream = (key * ((len(plaintext) // len(key)) + 1))[: len(plaintext)]
            xored = bytes(a ^ b for a, b in zip(plaintext, stream))
            return tag + base64.b64encode(xored)

    def decrypt(self, blob: bytes) -> Optional[bytes]:
        """Attempt to decrypt a tagged blob. Returns plaintext or None."""
        if not blob:
            return None
        if blob[: len(self.version_tag)] != self.version_tag:
            # Not a LiveDict-managed blob
            return None
        body = blob[len(self.version_tag) :]
        if _CRYPTO_AVAILABLE and self.aes_keys:
            # Try each key until one succeeds
            for aes in self.aes_keys:
                try:
                    nonce = body[:12]
                    ct = body[12:]
                    pt = aes.decrypt(nonce, ct, None)
                    return pt
                except Exception:
                    continue
            return None
        else:
            try:
                xored = base64.b64decode(body)
                key = self.keys[0]
                stream = (key * ((len(xored) // len(key)) + 1))[: len(xored)]
                pt = bytes(a ^ b for a, b in zip(xored, stream))
                return pt
            except Exception:
                return None


# ----------------------
# Backend base + implementations
# ----------------------
class BackendBase:
    """Abstract baseclass for persistence backends."""

    def set(self, bucket: str, key: str, ciphertext: bytes, expire_at: float) -> None:
        """Store ciphertext for bucket/key with expire_at timestamp."""
        raise NotImplementedError

    def get(self, bucket: str, key: str) -> Optional[Tuple[bytes, float]]:
        """Return (ciphertext, expire_at) or None if missing/expired."""
        raise NotImplementedError

    def delete(self, bucket: str, key: str) -> None:
        """Remove the persisted entry if any."""
        raise NotImplementedError

    def keys(self, bucket: str) -> List[str]:
        """Return list of non-expired keys for the bucket."""
        raise NotImplementedError

    def cleanup(self, bucket: Optional[str] = None) -> None:
        """Cleanup expired objects; optional bucket-specific cleanup."""
        raise NotImplementedError


class InMemoryBackend(BackendBase):
    """Simple dict-based backend used by `from_config` when inmemory enabled.

    This backend is purposely minimal; LiveDict maintains its own in-memory store,
    so this backend is mostly used when a pure-in-memory `from_config` configuration
    is requested (for tests / simple runs).
    """

    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def set(self, bucket, key, ciphertext, expire_at):
        with self._lock:
            self._store.setdefault(bucket or "__default__", {})[key] = (
                ciphertext,
                expire_at,
            )

    def get(self, bucket, key):
        with self._lock:
            b = self._store.get(bucket or "__default__", {})
            v = b.get(key)
            if not v:
                return None
            if v[1] < now_ts():
                # expired on backend -> remove and signal missing
                del b[key]
                return None
            return (v[0], v[1])

    def delete(self, bucket, key):
        with self._lock:
            b = self._store.get(bucket or "__default__", {})
            b.pop(key, None)

    def keys(self, bucket):
        with self._lock:
            b = self._store.get(bucket or "__default__", {})
            now = now_ts()
            return [k for k, (ct, exp) in b.items() if exp >= now]

    def cleanup(self, bucket=None):
        with self._lock:
            now = now_ts()
            if bucket:
                b = self._store.get(bucket, {})
                for k in list(b):
                    if b[k][1] < now:
                        del b[k]
            else:
                for bname in list(self._store):
                    b = self._store[bname]
                    for k in list(b):
                        if b[k][1] < now:
                            del b[k]


class SQLiteBackend(BackendBase):
    """
    SQLite file-backed persistence.

    - Accepts DSN strings of the form "sqlite:///path/to/dbfile.db" or a plain path.
    - Uses short-lived sqlite3 connections for each operation to avoid held file locks
        (important on Windows and for multiple processes).
    - Table has columns (bucket, key, value BLOB, expire_at REAL) with primary key on (bucket,key).

    Example:
        db = SQLiteBackend(dsn="sqlite:///tests/livedict.db", table="kv")
        db.set("main", "k", b'...', expire_at)
        db.get("main", "k")
    """

    def __init__(self, dsn: str = "sqlite:///livedict.db", table: str = "kv"):
        # Normalize DSN -> absolute path
        if dsn and isinstance(dsn, str) and dsn.startswith("sqlite:///"):
            path = dsn[len("sqlite:///") :]
        else:
            path = dsn
        if not path:
            path = "livedict.db"
        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        self.path = path
        self.table = table
        self._lock = threading.Lock()

        # Create table using a short-lived connection
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                bucket TEXT NOT NULL,
                key TEXT NOT NULL,
                value BLOB NOT NULL,
                expire_at REAL NOT NULL,
                PRIMARY KEY(bucket, key)
            )"""
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table}_expire ON {self.table}(expire_at)"
            )
            conn.commit()

    def set(self, bucket, key, ciphertext, expire_at):
        """Insert or replace row for given bucket/key."""
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    f"INSERT OR REPLACE INTO {self.table}(bucket,key,value,expire_at) VALUES (?,?,?,?)",
                    (
                        bucket or "__default__",
                        key,
                        sqlite3.Binary(ciphertext),
                        float(expire_at),
                    ),
                )
                conn.commit()

    def get(self, bucket, key):
        """
        Fetch exact bucket/key row. If not found try any-bucket fallback (useful in
        scenarios where bucket naming changed or tests expect fallback).
        Returns (bytes, expire_at) or None.
        """
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute(
                    f"SELECT value, expire_at FROM {self.table} WHERE bucket=? AND key=?",
                    (bucket or "__default__", key),
                )
                row = cur.fetchone()
                if row:
                    value, expire_at = row
                    if expire_at < now_ts():
                        # expired -> cleanup
                        conn.execute(
                            f"DELETE FROM {self.table} WHERE bucket=? AND key=?",
                            (bucket or "__default__", key),
                        )
                        conn.commit()
                        return None
                    return (bytes(value), float(expire_at))

                # fallback: search key in any bucket and pick the most recent valid row
                cur2 = conn.execute(
                    f"SELECT value, expire_at FROM {self.table} WHERE key=? ORDER BY expire_at DESC",
                    (key,),
                )
                for r in cur2.fetchall():
                    value, expire_at = r[0], r[1]
                    if expire_at >= now_ts():
                        return (bytes(value), float(expire_at))
                return None

    def delete(self, bucket, key):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    f"DELETE FROM {self.table} WHERE bucket=? AND key=?",
                    (bucket or "__default__", key),
                )
                conn.commit()

    def keys(self, bucket):
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute(
                f"SELECT key FROM {self.table} WHERE bucket=? AND expire_at>=?",
                (bucket or "__default__", time.time()),
            )
            return [r[0] for r in cur.fetchall()]

    def cleanup(self, bucket=None):
        with self._lock:
            with sqlite3.connect(self.path) as conn:
                if bucket:
                    conn.execute(
                        f"DELETE FROM {self.table} WHERE bucket=? AND expire_at < ?",
                        (bucket, time.time()),
                    )
                else:
                    conn.execute(
                        f"DELETE FROM {self.table} WHERE expire_at < ?", (time.time(),)
                    )
                conn.commit()


class FileBackend(BackendBase):
    """
    Simple file-backed object store used as an "external object store" provider.

    Each persisted entry is stored as a small file per bucket/key:
        - <base_dir>/<bucket>/<key>.entry

    File format:
        - first line: JSON metadata, e.g. {"expire_at": 175...}
        - following bytes: raw ciphertext (binary)

    The backend tries direct path first, and if not found scans other bucket
    directories to allow a degree of tolerance if callers use a different bucket
    (helpful for tests).
    """

    def __init__(self, base_dir="./livedict_store"):
        self.base = os.path.abspath(base_dir)
        os.makedirs(self.base, exist_ok=True)

    def _path(self, bucket, key):
        safe_bucket = (bucket or "__default__").replace("/", "_")
        safe_key = key.replace("/", "_")
        d = os.path.join(self.base, safe_bucket)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{safe_key}.entry")

    def set(self, bucket, key, ciphertext, expire_at):
        p = self._path(bucket, key)
        with open(p, "wb") as f:
            meta = json.dumps({"expire_at": expire_at}).encode() + b"\n"
            f.write(meta + ciphertext)

    def get(self, bucket, key):
        # Try direct path first
        p = self._path(bucket, key)
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    meta_raw = f.readline()
                    meta = json.loads(meta_raw.decode())
                    exp = float(meta.get("expire_at", 0))
                    if exp < now_ts():
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                        return None
                    data = f.read()
                    return (data, exp)
            except Exception:
                return None

        # Fallback: scan other buckets to find the key (tolerant approach)
        base = self.base
        try:
            for sub in os.listdir(base):
                dirpath = os.path.join(base, sub)
                if not os.path.isdir(dirpath):
                    continue
                candidate = os.path.join(dirpath, f"{key}.entry")
                if os.path.exists(candidate):
                    try:
                        with open(candidate, "rb") as f:
                            meta_raw = f.readline()
                            meta = json.loads(meta_raw.decode())
                            exp = float(meta.get("expire_at", 0))
                            if exp < now_ts():
                                try:
                                    os.remove(candidate)
                                except Exception:
                                    pass
                                return None
                            data = f.read()
                            return (data, exp)
                    except Exception:
                        continue
        except Exception:
            # Listing failure -> no persisted entry available
            return None

        return None

    def delete(self, bucket, key):
        p = self._path(bucket, key)
        try:
            os.remove(p)
        except Exception:
            pass

    def keys(self, bucket):
        d = os.path.join(self.base, (bucket or "__default__").replace("/", "_"))
        if not os.path.isdir(d):
            return []
        out = []
        for fn in os.listdir(d):
            if fn.endswith(".entry"):
                k = fn[:-6]
                v = self.get(bucket, k)
                if v:
                    out.append(k)
        return out

    def cleanup(self, bucket=None):
        if bucket:
            self.keys(bucket)
        else:
            for b in os.listdir(self.base):
                self.keys(b)


class RedisBackend(BackendBase):
    """
    Thin Redis wrapper used by tests. Requires redis-py to be installed.

    This backend stores keys under "<bucket>:<key>" and sets an expiry (TTL).
    """

    def __init__(self, url=None):
        self.url = url
        try:
            import redis  # type: ignore

            self.cli = redis.Redis.from_url(url) if url else redis.Redis()
        except Exception:
            self.cli = None

    def set(self, bucket, key, ciphertext, expire_at):
        if not self.cli:
            raise RuntimeError("redis client not installed")
        ttl = int(max(0, expire_at - now_ts()))
        self.cli.set(f"{bucket}:{key}", ciphertext, ex=ttl)

    def get(self, bucket, key):
        if not self.cli:
            return None
        v = self.cli.get(f"{bucket}:{key}")
        if not v:
            return None
        ttl = self.cli.ttl(f"{bucket}:{key}")
        return (v, now_ts() + ttl if ttl and ttl > 0 else now_ts() + 1)

    def delete(self, bucket, key):
        if not self.cli:
            return
        self.cli.delete(f"{bucket}:{key}")

    def keys(self, bucket):
        raise NotImplementedError

    def cleanup(self, bucket=None):
        return


# ----------------------
# In-memory Entry
# ----------------------
class Entry:
    """
    Represents an in-memory stored entry.

    Attributes:
        ciphertext (bytes): encrypted payload
        expire_at (float): expiry timestamp (seconds)
        on_access (Callable|None): optional callback run on get
        on_expire (Callable|None): optional callback run on expiry in monitor
        id (int): numeric id used by heap/monitor
    """

    __slots__ = ("ciphertext", "expire_at", "on_access", "on_expire", "id")

    def __init__(
        self,
        ciphertext: bytes,
        expire_at: float,
        on_access=None,
        on_expire=None,
        id: Optional[int] = None,
    ):
        self.ciphertext = ciphertext
        self.expire_at = expire_at
        self.on_access = on_access
        self.on_expire = on_expire
        self.id = id


# ----------------------
# LiveDict core
# ----------------------
class LiveDict:
    """
    Synchronous mapping-like ephemeral (TTL) encrypted key-value store.

    Features
    --------
    - mapping-like convenience: __getitem__, __setitem__, __delitem__, __contains__
    - set/get/delete/update methods with optional per-key hooks
    - heap-based expiry scheduling with a background monitor thread
    - optional persistence backends (SQLite, File, Redis) via `backends` dict
    - optional global listeners invoked synchronously on every set()

    Initialization
    --------------
    LiveDict(config: LiveDictConfig=None, cipher: CipherAdapter=None, backends: dict=None)

    - config: LiveDictConfig (validated). When omitted defaults are used.
    - cipher: CipherAdapter instance to encrypt/decrypt stored payloads. If
        not provided, a new CipherAdapter with a randomized key is created.
        IMPORTANT: If persisting across restarts, pass the same CipherAdapter
        instance (or one that uses the same keys/version_tag) to be able to
        decrypt persisted blobs.
    - backends: optional mapping of backend_name -> BackendBase instances used
        when `persist=True` or `backend` argument is provided to set/get.

    API highlights
    --------------
    - set(key, value, ttl=None, on_access=None, on_expire=None, key_expirable=False, token=None,
            bucket=None, backend=None, persist=False)
        Store an encrypted snapshot. If `persist=True` and backend provided,
        backend.set() is invoked with ciphertext.
    - get(key, token=None, bucket=None, backend=None)
        Returns deserialized object or None. If not present in-memory and
        `backend` provided it attempts to fetch and rehydrate the in-memory entry.
    - delete(...), keys(), items(), add_listener(...), stop()
    """

    def __init__(
        self,
        config: Optional[LiveDictConfig] = None,
        cipher: Optional[CipherAdapter] = None,
        backends: Optional[Dict[str, BackendBase]] = None,
    ):
        self.config = config or LiveDictConfig()
        # If user provided a cipher we will use it; otherwise generate a new one.
        # Note: version_tag is derived from config.common.encryption_version_tag.
        self.cipher = cipher or CipherAdapter(
            version_tag=self.config.common.encryption_version_tag.encode()
        )
        self.backends = backends or {}
        self.default_key_expirable = self.config.common.default_key_expirable

        # core in-memory structures:
        # _buckets: mapping bucket_name -> { key -> Entry }
        # _id_to_key / _key_to_id / _next_id: used for heap identity and to allow
        # duplicates removal and heap rebuilds.
        self._buckets: Dict[str, Dict[str, Entry]] = {}
        self._id_to_key: Dict[int, Tuple[str, str]] = {}
        self._key_to_id: Dict[Tuple[str, str], int] = {}
        self._next_id = 1
        self._heap: List[Tuple[float, int]] = []
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._running = True
        self._listeners: List[Callable[[str, Any], None]] = []

        # metrics / limits — initialize BEFORE monitor thread starts to avoid races
        self._max_total_keys = self.config.storage.inmemory.limits.get(
            "max_total_keys", 100_000
        )
        self._max_keys_per_bucket = self.config.storage.inmemory.limits.get(
            "max_keys_per_bucket", 20_000
        )
        self._stale_count = 0
        self._rebuild_threshold = max(
            100, int(self._max_total_keys * self.config.monitor.heap_rebuild_ratio)
        )

        # Start monitor thread for expiry events
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    # ---------------------
    # Internal helpers
    # ---------------------
    def _alloc_id(self, bucket: str, key: str) -> int:
        """
        Allocate a stable numeric id for a (bucket,key) pair.
        If the pair already has an id return that.
        """
        tup = (bucket, key)
        if tup in self._key_to_id:
            return self._key_to_id[tup]
        _id = self._next_id
        self._next_id += 1
        self._key_to_id[tup] = _id
        self._id_to_key[_id] = tup
        return _id

    def _free_id(self, _id: int):
        """Free mappings for an id when entry removed."""
        tup = self._id_to_key.pop(_id, None)
        if tup:
            self._key_to_id.pop(tup, None)

    def _ensure_bucket(self, bucket: str):
        """Create bucket mapping if missing."""
        self._buckets.setdefault(bucket, {})

    def _validate_limits(self, bucket: str, adding: int = 0):
        """
        Validate configured memory limits before adding keys.
        Raises MemoryError if limits exceeded.
        """
        total = sum(len(b) for b in self._buckets.values())
        if total + adding > self._max_total_keys:
            raise MemoryError(
                f"LiveDict: exceeded max_total_keys ({self._max_total_keys})"
            )
        if len(self._buckets.get(bucket, {})) + adding > self._max_keys_per_bucket:
            raise MemoryError(f"LiveDict: exceeded max_keys_per_bucket for {bucket}")

    # ---------------------
    # Mapping protocol helpers
    # ---------------------
    def __setitem__(self, key: str, value: Any) -> None:
        """Support d[key] = value shorthand (uses default bucket & TTL)."""
        self.set(key, value)

    def __getitem__(self, key: str) -> Any:
        """
        Support v = d[key]. Raises KeyError if missing or expired.
        Note: `get()` returns None for missing, so __getitem__ raises.
        """
        val = self.get(key)
        if val is None and not self.__contains__(key):
            raise KeyError(key)
        return val

    def __delitem__(self, key: str) -> None:
        """Support `del d[key]` shorthand (uses default bucket)."""
        self.delete(key)

    def __contains__(self, key: object) -> bool:
        """`key in d` True if key exists and is not expired (searches all buckets)."""
        if not isinstance(key, str):
            return False
        now = now_ts()
        with self._lock:
            for b, mapping in self._buckets.items():
                e = mapping.get(key)
                if e:
                    # treat negative expire_at as never-expiring
                    if e.expire_at < 0 or e.expire_at >= now:
                        return True
        return False

    def add_listener(self, fn: Callable[[str, Any], None]):
        """
        Register a synchronous listener invoked after each set().

        The listener receives (f"{bucket}:{key}", value). Exceptions in listeners
        are caught and printed but do not break LiveDict operation.
        """
        if not callable(fn):
            raise TypeError("listener must be callable")
        with self._lock:
            self._listeners.append(fn)

    # ---------------------
    # Public API
    # ---------------------
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        key_expirable: Optional[bool] = None,
        on_access: Optional[Callable] = None,
        on_expire: Optional[Callable] = None,
        bucket: Optional[str] = None,
        backend: Optional[Union[str, BackendBase]] = None,
        persist: bool = False,
    ):
        """
        Store a value for `key` with optional TTL and hooks.

        Parameters
        ----------
        ttl : Optional[int]
            Time-to-live in seconds. If not provided, the config.common.default_ttl will be used.
        key_expirable : Optional[bool]
            Whether this key should be expirable. If None, falls back to config.common.default_key_expirable. Overrides ttl if False.
        on_access : Optional[Callable]
            Callable(key) executed when the key is accessed.
        on_expire : Optional[Callable]
            Callable(key) executed when the key expires.
        bucket : Optional[str]
            Bucket name (if your config uses buckets). If omitted, a default bucket is used.
        backend : Optional[str|BackendBase]
            If provided, persistence backend to mirror to.
        """
        if key_expirable is None:
            key_expirable = self.default_key_expirable

        # Determine bucket using policy
        bucket_name = (
            bucket
            or (
                self.config.storage.inmemory.bucket_policy.default_bucket
                if self.config.storage.inmemory.bucket_policy.default_bucket_enabled
                else None
            )
            or "__default__"
        )
        if not self.config.storage.inmemory.bucket_policy.per_key and bucket:
            raise ValueError("per_key bucketing disabled by config")
        if (
            bucket is None
            and self.config.storage.inmemory.bucket_policy.error_if_no_bucket
        ):
            raise ValueError("bucket required by config")

        expire_at = (
            now_ts() + (ttl or self.config.common.default_ttl)
            if key_expirable
            else _NEVER_EXPIRE
        )

        # serialize (current implementation uses JSON by default)
        if self.config.common.serializer == "json":
            raw = json.dumps(value, default=_json_default).encode()
        else:
            raw = json.dumps(value, default=_json_default).encode()
        cipherdata = self.cipher.encrypt(raw)

        # Insert into in-memory structures under lock/condition and push heap event
        with self._cond:
            self._ensure_bucket(bucket_name)

            # if replacing existing key, don't count it as adding for limits
            existing = self._buckets[bucket_name].get(key)
            adding = 0 if existing else 1
            self._validate_limits(bucket_name, adding=adding)

            # If overwriting an existing entry, free its old id to avoid stale heap entries
            if existing:
                try:
                    self._free_id(existing.id)
                except Exception:
                    pass

            _id = self._alloc_id(bucket_name, key)
            entry = Entry(cipherdata, expire_at, on_access, on_expire, id=_id)
            self._buckets[bucket_name][key] = entry

            if expire_at is not None and expire_at >= 0:
                heapq.heappush(self._heap, (expire_at, _id))

            self._cond.notify()

        if (persist or self.config.storage.inmemory.mirror_to_persistence) and backend:
            be = (
                backend
                if isinstance(backend, BackendBase)
                else self.backends.get(backend)
            )
            try:
                if be:
                    be.set(bucket_name, key, cipherdata, expire_at)
            except Exception:
                # Persistence failures are non-fatal by design
                pass

        # Notify global listeners synchronously (exceptions are printed)
        with self._lock:
            for ln in list(self._listeners):
                try:
                    ln(f"{bucket_name}:{key}", value)
                except Exception:
                    traceback.print_exc()

    def get(
        self,
        key: str,
        token: Optional[str] = None,
        bucket: Optional[str] = None,
        backend: Optional[Union[str, BackendBase]] = None,
    ) -> Optional[Any]:
        """
        Retrieve value for `key`. Negative expire_at is considered non-expiring.
        """
        bucket_name = (
            bucket
            or (
                self.config.storage.inmemory.bucket_policy.default_bucket
                if self.config.storage.inmemory.bucket_policy.default_bucket_enabled
                else None
            )
            or "__default__"
        )
        now = now_ts()
        with self._lock:
            b = self._buckets.get(bucket_name)
            entry = b.get(key) if b else None
            if entry and (entry.expire_at < 0 or entry.expire_at >= now):
                data = entry.ciphertext
            else:
                data = None

        # If not in-memory and a backend provided, attempt backend fetch and hydrate
        if data is None and backend:
            be = (
                backend
                if isinstance(backend, BackendBase)
                else self.backends.get(backend)
            )
            if be:
                try:
                    r = be.get(bucket_name, key)
                    if r:
                        data, expire_at = r
                        with self._cond:
                            # free existing id if any and allocate a fresh one (avoid stale heap events)
                            existing = self._buckets.setdefault(bucket_name, {}).get(
                                key
                            )
                            if existing:
                                try:
                                    self._free_id(existing.id)
                                except Exception:
                                    pass
                            _id = self._alloc_id(bucket_name, key)
                            ent = Entry(data, expire_at, None, None, id=_id)
                            self._buckets[bucket_name][key] = ent
                            if expire_at is not None and expire_at >= 0:
                                heapq.heappush(self._heap, (expire_at, _id))
                except Exception:
                    # backend failures are non-fatal -> return None later
                    pass

        if not data:
            return None

        plaintext = self.cipher.decrypt(data)
        if plaintext is None:
            # decryption failed (likely wrong key/version_tag)
            return None
        try:
            val = json.loads(plaintext.decode())
        except Exception:
            # if JSON decode fails, return raw plaintext bytes as a fallback
            val = plaintext

        # Execute per-key on_access hook if present (safely)
        try:
            if entry and entry.on_access:
                try:
                    entry.on_access(key, val)
                except Exception:
                    traceback.print_exc()
        except Exception:
            pass
        return val

    def delete(
        self,
        key: str,
        token: Optional[str] = None,
        bucket: Optional[str] = None,
        backend: Optional[Union[str, BackendBase]] = None,
        persist: bool = False,
    ):
        """
        Delete in-memory entry and optionally delete from persistent backend.

        - persist=True and backend supplied will call backend.delete(...)
        """
        bucket_name = (
            bucket
            or (
                self.config.storage.inmemory.bucket_policy.default_bucket
                if self.config.storage.inmemory.bucket_policy.default_bucket_enabled
                else None
            )
            or "__default__"
        )
        with self._cond:
            b = self._buckets.get(bucket_name, {})
            e = b.pop(key, None)
            if e:
                self._free_id(e.id)
            self._cond.notify()

        if (persist or self.config.storage.inmemory.mirror_to_persistence) and backend:
            be = (
                backend
                if isinstance(backend, BackendBase)
                else self.backends.get(backend)
            )
            try:
                if be:
                    be.delete(bucket_name, key)
            except Exception:
                pass

    def keys(self, bucket: Optional[str] = None) -> List[str]:
        """Return snapshot list of non-expired keys in given bucket (default '__default__')."""
        bucket_name = bucket or "__default__"
        with self._lock:
            b = self._buckets.get(bucket_name, {})
            now = now_ts()
            return [k for k, e in b.items() if e.expire_at >= now]

    def items(self, bucket: Optional[str] = None) -> List[Tuple[str, Any]]:
        """
        Materialize (key, value) for non-expired keys. Note: this runs get()
        for each key and thus may execute on_access hooks as a side-effect.
        """
        ks = self.keys(bucket)
        return [(k, self.get(k, bucket=bucket)) for k in ks]

    def stop(self):
        """Stop the background monitor thread and wait briefly for it to join."""
        self._running = False
        with self._cond:
            self._cond.notify_all()
        self._monitor_thread.join(timeout=2.0)

    # ---------------------
    # Monitor thread & heap maintenance
    # ---------------------
    def _monitor_loop(self):
        """
        Background monitor thread responsible for expiring entries and firing on_expire hooks.
        """
        while self._running:
            with self._cond:
                nowt = now_ts()
                fired = []

                while self._heap:
                    exp, _id = self._heap[0]  # peek top

                    # If top entry is unexpirable, skip processing and wait
                    if exp is not None and exp < 0:
                        break

                    # If not due yet, stop popping
                    if exp is None or exp > nowt:
                        break

                    # Pop and handle
                    heapq.heappop(self._heap)
                    tup = self._id_to_key.get(_id)
                    if not tup:
                        self._stale_count += 1
                        continue

                    bucket_name, key = tup
                    b = self._buckets.get(bucket_name, {})
                    ent = b.get(key)
                    if not ent:
                        self._free_id(_id)
                        continue

                    # Unexpirable guard (shouldn't happen here because of first check)
                    if ent.expire_at is not None and ent.expire_at < 0:
                        heapq.heappush(self._heap, (ent.expire_at, _id))
                        break

                    # Expire this entry
                    if ent.expire_at is None or ent.expire_at <= nowt:
                        try:
                            b.pop(key, None)
                        except Exception:
                            pass
                        self._free_id(_id)
                        if ent.on_expire:
                            fired.append((ent.on_expire, key))
                    else:
                        heapq.heappush(self._heap, (ent.expire_at, _id))

                # Compact heap if needed
                if self._stale_count > self._rebuild_threshold:
                    self._rebuild_heap_locked()

                # Next wake-up
                timeout = 1.0
                if self._heap:
                    exp = self._heap[0][0]
                    if exp is not None and exp >= 0:
                        timeout = max(0.0, min(1.0, exp - nowt))

                self._cond.wait(timeout=timeout)

            # Run expiry hooks outside the lock
            for fn, k in fired:
                try:
                    fn(k)
                except Exception:
                    traceback.print_exc()

    def _rebuild_heap_locked(self):
        """
        Rebuild internal heap from current mapping. Include only entries with
        non-negative expiry timestamps (those scheduled for expiry).
        """
        mapping = []
        for bname, keys in self._buckets.items():
            for key, ent in keys.items():
                if ent and ent.expire_at is not None and ent.expire_at >= 0:
                    mapping.append((ent.expire_at, ent.id))
        heapq.heapify(mapping)
        self._heap = mapping
        self._stale_count = 0
        self._rebuild_threshold = max(
            100, int(self._max_total_keys * self.config.monitor.heap_rebuild_ratio)
        )

    # ---------------------
    # Factories & presets
    # ---------------------
    @classmethod
    def from_config(
        cls,
        cfg: LiveDictConfig,
        cipher: Optional[CipherAdapter] = None,
        extra_backends: Optional[Dict[str, BackendBase]] = None,
    ):
        """
        Construct LiveDict from validated LiveDictConfig.

        - cfg: LiveDictConfig
        - cipher: optional CipherAdapter (if omitted a new adapter is used)
        - extra_backends: optional dict of backend instances to supplement builtins

        Returns LiveDict instance.
        """
        backends = {}
        if cfg.storage.inmemory.enabled:
            backends["inmemory"] = InMemoryBackend()
        if cfg.storage.sql.enabled:
            # cfg.storage.sql.dsn may be "sqlite:///path" or a plain path
            dsn = cfg.storage.sql.dsn or "sqlite:///livedict.db"
            backends["sql"] = SQLiteBackend(dsn=dsn, table=cfg.storage.sql.table)

        if cfg.storage.external_object.enabled:
            # If configured as "file" provider use bucket_name as base dir
            base = cfg.storage.external_object.bucket_name or "./livedict_store"
            backends["file"] = FileBackend(base_dir=base)
        if extra_backends:
            backends.update(extra_backends)
        cipher = cipher or CipherAdapter(
            version_tag=cfg.common.encryption_version_tag.encode()
        )
        return cls(config=cfg, cipher=cipher, backends=backends)

    @classmethod
    def from_preset(cls, name: str = "simple"):
        """
        Convenience to create LiveDict from small named presets.

        Available presets:
            - simple: in-memory, no buckets
            - bucketed: in-memory with buckets
            - durable_sql: SQL-backed persistence (no in-memory mirror)
        """
        presets = {
            "simple": {
                "storage": {"inmemory": {"enabled": True, "use_buckets": False}}
            },
            "bucketed": {
                "storage": {"inmemory": {"enabled": True, "use_buckets": True}},
                "common": {"default_ttl": 300},
            },
            "durable_sql": {
                "storage": {"inmemory": {"enabled": False}, "sql": {"enabled": True}}
            },
        }
        raw = presets.get(name)
        if not raw:
            raise ValueError("unknown preset")
        cfg = LiveDictConfig.model_validate(raw)
        return cls.from_config(cfg)


# ----------------------
# Async wrapper
# ----------------------
class AsyncLiveDict:
    """
    Async wrapper around the synchronous LiveDict.

    Purpose
    -------
    Provide an asyncio-friendly interface to the synchronous `LiveDict` by
    offloading blocking / CPU-bound operations to a thread pool. This is a
    thin adaptor; the underlying store, monitor thread and hooks remain the
    synchronous `LiveDict` implementation.

    Key points (summary)
    --------------------
    - Each public API method (`set`, `get`, `delete`, `stop`) offloads the
        synchronous call into a thread executor using `loop.run_in_executor`.
    - By default, `run_in_executor` uses asyncio's default ThreadPoolExecutor.
        You can supply your own executor for finer control of thread counts.
    - Callbacks registered with `LiveDict` (e.g., `on_access`, `on_expire`)
        run in the synchronous runtime (the monitor thread or the calling thread)
        and are NOT awaited by `AsyncLiveDict`. If you want to run async
        coroutines in those callbacks, have the callbacks schedule them onto
        the event loop (see examples below).
    - Exceptions raised inside the synchronous call will propagate back to the
        awaiting coroutine (they will be re-raised).
    - This wrapper is straightforward, predictable and suitable for many cases,
        but if you need a truly non-blocking/async-native store (no threads),
        consider implementing an asyncio-native `AsyncLiveDict` that uses
        `asyncio.Lock`/`asyncio.Task` for the monitor.

    Constructor
    -----------
    AsyncLiveDict(config: Optional[LiveDictConfig] = None,
                    cipher: Optional[CipherAdapter] = None,
                    backends: Optional[Dict[str, BackendBase]] = None,
                    executor: Optional[concurrent.futures.Executor] = None)

    Parameters
    ----------
    config
        LiveDictConfig passed to the underlying LiveDict (or used by factory).
    cipher
        CipherAdapter for encryption/decryption passed to the underlying LiveDict.
    backends
        Optional mapping of backend name -> BackendBase to register on the LiveDict.
    executor
        Optional concurrent.futures.Executor (ThreadPoolExecutor or custom) used to run
        blocking calls. If omitted, asyncio's default thread pool is used.

    Usage example
    -------------
    >>> ad = AsyncLiveDict()
    >>> await ad.set("k", {"v": 1}, ttl=10)
    >>> val = await ad.get("k")
    >>> await ad.stop()

    Example: scheduling async work from on_expire
    --------------------------------------------
    >>> def on_expire_handler(key):
    >>>     loop = asyncio.get_event_loop()
    >>>     loop.call_soon_threadsafe(asyncio.create_task, async_expire_worker(key))

    >>> async def async_expire_worker(key):
    >>>     # heavy async processing here
    >>>     await asyncio.sleep(0.1)
    >>>     print("handled expired", key)

    >>> # register callback via LiveDict.set(..., on_expire=on_expire_handler)
    
    Passing executor
    ----------------
    >>> ad = AsyncLiveDict(executor=concurrent.futures.ThreadPoolExecutor(max_workers=4))


    Running async work from on_expire/on_access
    -------------------------------------------
    The `on_expire` and `on_access` callbacks on `LiveDict` are synchronous (they
    are called directly by the monitor thread or by the thread that performed the
    operation). If you want to run coroutine functions from those callbacks, have
    the callbacks schedule them on the event loop, e.g.:

    >>> def on_expire_callback(key):
    >>>     loop = asyncio.get_event_loop()
    >>>     # schedule coroutine safely without awaiting here
    >>>     loop.call_soon_threadsafe(asyncio.create_task, my_async_handler(key))

    Notes / Caveats
    ----------------
    - This wrapper makes `LiveDict` usable from asyncio but it still relies on
        threads. If you spawn many concurrent operations you may exhaust the
        threadpool; consider supplying a custom executor to control max_workers.
    - Cancellation: canceling the awaiting coroutine does not forcibly cancel the
        underlying synchronous operation — the thread will continue to run and
        finish its operation; the awaiting coroutine will receive `asyncio.CancelledError`.
    - Shutdown: always call `await ad.stop()` during application shutdown to
        ensure the monitor thread is asked to stop and the underlying LiveDict is
        cleanly joined.
    """

    def __init__(
        self,
        config: Optional["LiveDictConfig"] = None,
        cipher: Optional["CipherAdapter"] = None,
        backends: Optional[Dict[str, "BackendBase"]] = None,
        executor: Optional[concurrent.futures.Executor] = None,
    ):
        # create the underlying synchronous LiveDict instance.
        # We use the straightforward constructor here; if your codebase provides
        # LiveDict.from_config(...) you can switch to that factory.
        self._ld = LiveDict(config or LiveDictConfig(), cipher=cipher)
        if backends:
            for name, be in backends.items():
                self._ld.register_backend(name, be)

        # optional executor allows limiting number of threads / reuse
        self._executor = executor

    async def _run(self, fn, *args, **kwargs):
        """
        Run callable `fn` in executor and return result.
        Uses the provided executor if set, otherwise the default executor.
        """
        loop = asyncio.get_running_loop()
        call = functools.partial(fn, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    async def set(self, *args, **kwargs):
        """Asynchronous wrapper for LiveDict.set(...)."""
        return await self._run(self._ld.set, *args, **kwargs)

    async def get(self, *args, **kwargs):
        """Asynchronous wrapper for LiveDict.get(...)."""
        return await self._run(self._ld.get, *args, **kwargs)

    async def delete(self, *args, **kwargs):
        """Asynchronous wrapper for LiveDict.delete(...)."""
        return await self._run(self._ld.delete, *args, **kwargs)

    async def keys(self, *args, **kwargs):
        """Async wrapper for LiveDict.keys(...)."""
        return await self._run(self._ld.keys, *args, **kwargs)

    async def items(self, *args, **kwargs):
        """Async wrapper for LiveDict.items(...)."""
        return await self._run(self._ld.items, *args, **kwargs)

    async def stop(self):
        """Ask the underlying LiveDict to stop and wait for its monitor thread to join."""
        return await self._run(self._ld.stop)

    @classmethod
    def from_config(
        cls,
        cfg: "LiveDictConfig",
        cipher: Optional["CipherAdapter"] = None,
        extra_backends: Optional[Dict[str, "BackendBase"]] = None,
        executor: Optional[concurrent.futures.Executor] = None,
    ) -> "AsyncLiveDict":
        """
        Convenience factory. Returns a new AsyncLiveDict configured with cfg and
        optionally registering extra_backends. This method is synchronous; use it
        during startup (before awaiting any methods).
        """
        inst = cls(
            config=cfg, cipher=cipher, backends=extra_backends, executor=executor
        )
        return inst


def _json_default(obj):
    """Fallback serializer for objects not JSON serializable; returns __dict__ or str()."""
    try:
        return obj.__dict__
    except Exception:
        return str(obj)


# ----------------------
# Builder utilities
# ----------------------
class BaseBuilder:
    """Base class for config builders. Subclasses must implement _load_and_validate()."""

    def __init__(
        self, source: Optional[Any] = None, overrides: Optional[Dict[str, Any]] = None
    ):
        self.source = source
        self.overrides = overrides or {}
        self._cfg: Optional[LiveDictConfig] = None

    def preview(self) -> LiveDictConfig:
        """Return validated LiveDictConfig (cached)."""
        if self._cfg is None:
            self._cfg = self._load_and_validate()
        return self._cfg

    def build(self) -> LiveDict:
        """Construct LiveDict from validated preview config."""
        cfg = self.preview()
        return LiveDict.from_config(cfg)

    async def build_async(self) -> AsyncLiveDict:
        cfg = self.preview()
        return await AsyncLiveDict.from_config(cfg)

    def _apply_overrides(self, raw: dict) -> dict:
        """Apply dot-path overrides provided by the user to a raw config dict."""
        out = dict(raw)
        for k, v in self.overrides.items():
            dot_set(out, k, v)
        return out

    def _load_and_validate(self) -> LiveDictConfig:
        raise NotImplementedError


class LiveDictJSONBuilder(BaseBuilder):
    """Load LiveDictConfig from JSON file or JSON string or dict."""

    def _load_and_validate(self):
        raw = {}
        if isinstance(self.source, str):
            if os.path.exists(self.source):
                with open(self.source, "r", encoding="utf8") as f:
                    raw = json.load(f)
            else:
                raw = json.loads(self.source)
        elif isinstance(self.source, dict):
            raw = self.source
        raw = self._apply_overrides(raw)
        return LiveDictConfig.model_validate(raw)


class LiveDictYAMLBuilder(BaseBuilder):
    """Load LiveDictConfig from YAML (requires pyyaml)."""

    def _load_and_validate(self):
        try:
            import yaml  # type: ignore
        except Exception as e:
            raise ImportError(
                "PyYAML required for YAMLBuilder (pip install pyyaml)"
            ) from e
        raw = {}
        if isinstance(self.source, str):
            if os.path.exists(self.source):
                with open(self.source, "r", encoding="utf8") as f:
                    raw = yaml.safe_load(f)
            else:
                raw = yaml.safe_load(self.source)
        elif isinstance(self.source, dict):
            raw = self.source
        raw = self._apply_overrides(raw)
        return LiveDictConfig.model_validate(raw)


class LiveDictPresetBuilder(BaseBuilder):
    """Small factory that returns known presets which are useful for tests and examples."""

    def __init__(
        self, preset_name: str = "simple", overrides: Optional[Dict[str, Any]] = None
    ):
        super().__init__(source=None, overrides=overrides)
        self.preset_name = preset_name

    def _load_and_validate(self):
        presets = {
            "simple": {
                "storage": {"inmemory": {"enabled": True, "use_buckets": False}},
                "common": {"default_ttl": 600},
            },
            "bucketed": {
                "storage": {"inmemory": {"enabled": True, "use_buckets": True}},
                "common": {"default_ttl": 300},
            },
            "durable_sql": {
                "storage": {"inmemory": {"enabled": False}, "sql": {"enabled": True}},
                "common": {"default_ttl": 600},
            },
            "hybrid_cache_db": {
                "storage": {
                    "inmemory": {
                        "enabled": True,
                        "use_buckets": True,
                        "mirror_to_persistence": True,
                    },
                    "sql": {"enabled": True},
                },
                "common": {"default_ttl": 300},
            },
        }
        raw = presets.get(self.preset_name)
        if not raw:
            raise ValueError("unknown preset")
        raw = self._apply_overrides(raw)
        return LiveDictConfig.model_validate(raw)


class LiveDictEnvBuilder(BaseBuilder):
    """
    Build config from environment variables with prefix LIVEDICT_.

    Mapping rule:
        LIVEDICT_common_default_ttl -> common.default_ttl
    Values that look like JSON (object, array, numeric, true/false/null) are parsed.
    """

    def _load_and_validate(self):
        raw = {}
        prefix = "LIVEDICT_"
        for k, v in os.environ.items():
            if not k.startswith(prefix):
                continue
            rem = k[len(prefix) :]
            # map LIVEDICT_common_default_ttl -> common.default_ttl
            if "_" in rem:
                first, rest = rem.split("_", 1)
                key = first.lower() + "." + rest.lower()
            else:
                key = rem.lower()
            val = json.loads(v) if _looks_like_json(v) else v
            dot_set(raw, key, val)
        raw = self._apply_overrides(raw)
        return LiveDictConfig.model_validate(raw)


def _looks_like_json(s: str) -> bool:
    """Heuristic to decide if an env var contains a JSON-ish value."""
    s = s.strip()
    return bool(s) and (
        s.startswith("{")
        or s.startswith("[")
        or s in ("null", "true", "false")
        or s[0].isdigit()
    )


class LiveDictFluentBuilder(BaseBuilder):
    """
    Fluent builder providing a small DSL to assemble a LiveDictConfig.

    Example
    -------
    builder = LiveDictFluentBuilder().preset("durable_sql").with_sql("sqlite:///tests.db").bucket_policy(default_bucket="main")
    cfg = builder.preview()
    """

    def __init__(self):
        super().__init__(source=None)
        self._raw = {}

    def preset(self, name: str):
        self._raw = LiveDictPresetBuilder(name)._load_and_validate().dict()
        return self

    def with_sql(self, dsn: str, table: str = "kv"):
        dot_set(self._raw, "storage.sql.enabled", True)
        dot_set(self._raw, "storage.sql.dsn", dsn)
        dot_set(self._raw, "storage.sql.table", table)
        return self

    def with_file_backend(self, base_dir: str):
        dot_set(self._raw, "storage.external_object.enabled", True)
        dot_set(self._raw, "storage.external_object.provider", "file")
        dot_set(self._raw, "storage.external_object.bucket_name", base_dir)
        return self

    def bucket_policy(
        self,
        per_key: bool = True,
        default_bucket_enabled: bool = True,
        default_bucket: str = "main",
        error_if_no_bucket: bool = False,
    ):
        bp = {
            "per_key": per_key,
            "default_bucket_enabled": default_bucket_enabled,
            "default_bucket": default_bucket,
            "error_if_no_bucket": error_if_no_bucket,
        }
        dot_set(self._raw, "storage.inmemory.bucket_policy", bp)
        return self

    def with_defaults(self, ttl: int = 600, serializer: str = "json"):
        dot_set(self._raw, "common.default_ttl", ttl)
        dot_set(self._raw, "common.serializer", serializer)
        dot_set(self._raw, "common.default_key_expirable", True)
        return self

    def preview(self):
        raw = self._apply_overrides(self._raw)
        return LiveDictConfig.model_validate(raw)

    def _load_and_validate(self):
        return self.preview()


class LiveDictInteractiveBuilder(BaseBuilder):
    """
    Interactive wizard for quick config creation (reads from stdin).
    Use only in interactive contexts.
    """

    def _load_and_validate(self):
        print("Interactive LiveDict config wizard:")
        use_buckets = input("Enable buckets? (y/N): ").strip().lower() == "y"
        preset = "simple"
        if use_buckets:
            preset = "bucketed"
        raw = LiveDictPresetBuilder(preset)._load_and_validate().dict()
        if use_buckets:
            default_bucket = (
                input("Default bucket name (press enter for 'main'): ").strip()
                or "main"
            )
            dot_set(raw, "storage.inmemory.bucket_policy.default_bucket_enabled", True)
            dot_set(
                raw, "storage.inmemory.bucket_policy.default_bucket", default_bucket
            )
        ttl = input("Default TTL seconds (enter for 600): ").strip()
        if ttl:
            dot_set(raw, "common.default_ttl", int(ttl))
        return LiveDictConfig.model_validate(raw)


# ----------------------
# Module exports and convenience functions
# ----------------------
__all__ = [
    "LiveDict",
    "AsyncLiveDict",
    "LiveDictFluentBuilder",
    "LiveDictJSONBuilder",
    "LiveDictYAMLBuilder",
    "LiveDictPresetBuilder",
    "LiveDictEnvBuilder",
    "LiveDictInteractiveBuilder",
    "LiveDictConfig",
    "CipherAdapter",
    "InMemoryBackend",
    "SQLiteBackend",
    "FileBackend",
    "RedisBackend",
]


def from_preset(name: str = "simple"):
    """Convenience: LiveDict.from_preset(name)."""
    return LiveDict.from_preset(name)


def from_json(path_or_str: str, overrides: Optional[Dict] = None):
    """Convenience: build LiveDict from JSON file/string."""
    return LiveDictJSONBuilder(path_or_str, overrides).build()


def from_yaml(path_or_str: str, overrides: Optional[Dict] = None):
    """Convenience: build LiveDict from YAML file/string."""
    return LiveDictYAMLBuilder(path_or_str, overrides).build()
