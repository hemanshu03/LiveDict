"""
livedict.core
=============

Secure, in-memory (and optionally Redis-backed) key-value store with:

- AES-GCM encryption
- Automatic TTL-based expiry
- Sandboxed hooks on access/expire
- Thread-safe operations
- Optional Redis persistence
"""

import threading
import time
import json
import redis
import os
from typing import Callable, Any, Optional, Dict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from multiprocessing import Process, Pipe
import platform


class SandboxTimeout(Exception):
    """Raised when a sandboxed hook exceeds its configured timeout."""
    pass


class SandboxedHookRunner:
    """
    Executes callback hooks in isolated processes with timeout and memory limits.

    Parameters
    ----------
    timeout_seconds : int, default=1
        Maximum execution time for each hook in seconds.
    max_memory_mb : int, default=50
        Memory limit per process (MB). Unix-only.
    """

    def __init__(self, timeout_seconds: int = 1, max_memory_mb: int = 50):
        self.timeout = timeout_seconds
        self.max_memory = max_memory_mb * 1024 * 1024
        self._is_unix = platform.system() != "Windows"

    def _target(self, func, conn, *args, **kwargs):
        """
        Target process for hook execution with optional memory limit (Unix only).
        Sends (success, result/exception) back through a pipe.
        """
        if self._is_unix:
            try:
                import resource

                resource.setrlimit(
                    resource.RLIMIT_AS, (self.max_memory, self.max_memory)
                )
            except Exception:
                raise NotImplementedError(
                    "Memory-limited sandboxing is not supported on Windows yet."
                )
        try:
            result = func(*args, **kwargs)
            conn.send((True, result))
        except Exception as e:
            conn.send((False, e))
        finally:
            conn.close()

    def run(self, func: Callable, *args, **kwargs) -> Any:
        """
        Run a function in a sandboxed subprocess.

        Raises
        ------
        SandboxTimeout
            If the function execution exceeds the configured timeout.
        Exception
            Propagates any exception raised by the hook function.
        """
        parent_conn, child_conn = Pipe()
        p = Process(target=self._target, args=(func, child_conn) + args, kwargs=kwargs)
        p.start()
        p.join(self.timeout)
        if p.is_alive():
            p.terminate()
            raise SandboxTimeout(f"Function execution exceeded {self.timeout}s")
        success, payload = parent_conn.recv()
        if not success:
            raise payload
        return payload


class Entry:
    """
    Represents a stored value in LiveDict.

    Attributes
    ----------
    value : bytes
        Encrypted serialized value.
    expire_at : float
        Timestamp (epoch) when this entry expires.
    on_access : Callable, optional
        Hook executed on value retrieval.
    on_expire : Callable, optional
        Hook executed when the key expires.
    """
    def __init__(
        self,
        value: Any,
        expire_at: float,
        on_access: Optional[Callable] = None,
        on_expire: Optional[Callable] = None,
    ):
        self.value = value
        self.expire_at = expire_at
        self.on_access = on_access
        self.on_expire = on_expire


class LiveDict:
    """
    Encrypted, thread-safe dictionary with TTL-based expiry and optional Redis persistence.

    Parameters
    ----------
    default_ttl : int, default=600
        Default time-to-live in seconds for keys.
    redis_url : str, optional
        Redis connection URL (e.g., "redis://localhost:6379/0").
    enable_redis_support : bool, default=False
        Enable Redis persistence (requires `redis_url`).
    encryption_key : bytes, optional
        AES-GCM key (32 bytes). Auto-generated if None.
    """
    def __init__(
        self,
        default_ttl: int = 600,
        redis_url: Optional[str] = None,
        enable_redis_support: bool = False,
        encryption_key: Optional[bytes] = None,
    ):

        self.default_ttl = default_ttl
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._in_memory_store: Dict[str, Entry] = {}
        self._running = True
        self.runner = SandboxedHookRunner()

        # encryption setup
        if encryption_key is None:
            self._key = AESGCM.generate_key(bit_length=256)
        else:
            self._key = encryption_key
        self._aesgcm = AESGCM(self._key)

        # optional redis setup
        self.redis_enabled = enable_redis_support and redis_url is not None
        self.redis = (
            redis.StrictRedis.from_url(redis_url) if self.redis_enabled else None
        )

        # background thread for expiry
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def _encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aesgcm.encrypt(nonce, plaintext, None)

    def _decrypt(self, ciphertext: bytes) -> bytes:
        nonce, ct = ciphertext[:12], ciphertext[12:]
        return self._aesgcm.decrypt(nonce, ct, None)

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        on_access: Optional[Callable] = None,
        on_expire: Optional[Callable] = None,
    ):
        expire_at = time.time() + (ttl or self.default_ttl)
        raw = json.dumps(value).encode("utf-8")
        encrypted = self._encrypt(raw)
        entry = Entry(encrypted, expire_at, on_access, on_expire)

        with self._cond:
            self._in_memory_store[key] = entry
            self._cond.notify()

        if self.redis_enabled:
            self.redis.set(key, encrypted, ex=int(ttl or self.default_ttl))

    def get(self, key: str) -> Optional[Any]:
        if key in self._in_memory_store:
            entry = self._in_memory_store.get(key)
            if not entry or entry.expire_at < time.time():
                return None
            data = entry.value
        elif self.redis_enabled:
            data = self.redis.get(key)
            if not data:
                return None
        else:
            return None

        plaintext = self._decrypt(data)
        val = json.loads(plaintext.decode("utf-8"))

        if key in self._in_memory_store:
            entry = self._in_memory_store[key]
            if entry.on_access:
                self.runner.run(entry.on_access, key, val)

        return val

    def delete(self, key: str):
        with self._cond:
            self._in_memory_store.pop(key, None)
            self._cond.notify()
        if self.redis_enabled:
            self.redis.delete(key)

    def _monitor(self):
        while self._running:
            with self._cond:
                now = time.time()
                nearest = None
                for k, e in list(self._in_memory_store.items()):
                    if e.expire_at <= now:
                        self._in_memory_store.pop(k, None)
                        if e.on_expire:
                            try:
                                self.runner.run(e.on_expire, k)
                            except Exception:
                                pass
                    else:
                        if nearest is None or e.expire_at < nearest:
                            nearest = e.expire_at
                timeout = (nearest - now) if nearest else None
                if timeout is None or timeout < 0:
                    self._cond.wait(timeout=1)
                else:
                    self._cond.wait(timeout=timeout)

    def stop(self):
        self._running = False
        with self._cond:
            self._cond.notify_all()
        self._thread.join()
