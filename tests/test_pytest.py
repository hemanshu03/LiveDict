# tests/test_livedict.py
"""
Integration test suite for src.livedict.core

This file contains a collection of synchronous and asynchronous tests that exercise
the core LiveDict and backend implementations (in-memory, file, sqlite, optional redis).
The suite is written to be self-contained and deterministic for CI/local usage.

How to run
----------
From the project root:
    pytest -q tests/test_livedict.py

Notes
-----
- Redis tests are skipped automatically if redis-py is not installed or Redis is unreachable.
- The SQLite persistence tests use a deterministic shared cipher key so two separate
    LiveDict instances can decrypt each other's persisted blobs (simulating a restart).
- Temporary artifacts are created under ./tests/ and are cleaned where appropriate.
"""

from __future__ import annotations

import os
import time
import json
import shutil
import asyncio
import tempfile
import sqlite3
import pytest
from typing import Any, Dict

from src import (
    LiveDict,
    AsyncLiveDict,
    LiveDictPresetBuilder,
    LiveDictJSONBuilder,
    LiveDictYAMLBuilder,
    LiveDictFluentBuilder,
    LiveDictEnvBuilder,
    LiveDictInteractiveBuilder,
    LiveDictConfig,
    CipherAdapter,
    InMemoryBackend,
    SQLiteBackend,
    FileBackend,
    RedisBackend,
)

# ---------------------------------------------------------------------------
# Constants & test-target paths
# ---------------------------------------------------------------------------
TEST_DIR = os.path.abspath("./tests")
SQL_DB_PATH = os.path.join(TEST_DIR, "livedict_test.db")
FILE_BACKEND_DIR = os.path.join(TEST_DIR, "file_backend_store")
JSON_CFG_PATH = os.path.join(TEST_DIR, "livedict_config.json")
YAML_CFG_PATH = os.path.join(TEST_DIR, "livedict_config.yml")

# Use a deterministic 32-byte key for persistence tests so restarts can decrypt.
_SHARED_TEST_KEY = b"\x01" * 32
_SHARED_TEST_CIPHER = CipherAdapter(keys=[_SHARED_TEST_KEY], version_tag=b"LD1")


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def ensure_tests_dir():
    """
    Ensure a clean ./tests/ folder for this test session.

    - Removes previously-created artifacts that this suite controls.
    - Leaves the tests/ directory in place for inspection after the run.
    """
    print("\n[TEST FIXTURE] ensure_tests_dir: creating ./tests/ (clean)")
    if os.path.exists(TEST_DIR):
        # Remove known artifacts (leave the directory itself intact)
        for fn in ("livedict_test.db", "livedict_config.json", "livedict_config.yml"):
            p = os.path.join(TEST_DIR, fn)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        # remove file backend dir if exists
        if os.path.isdir(FILE_BACKEND_DIR):
            shutil.rmtree(FILE_BACKEND_DIR, ignore_errors=True)
    else:
        os.makedirs(TEST_DIR, exist_ok=True)
    yield
    print("\n[TEST FIXTURE] ensure_tests_dir: teardown (non-destructive)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_redis_client_or_skip():
    """
    Attempt to import and ping Redis. If not available, skip the test.
    Returns a connected client if reachable.
    """
    try:
        import redis  # type: ignore
    except Exception:
        pytest.skip("redis-py not installed; skipping Redis tests")
    cli = redis.Redis(host="localhost", port=6379, db=0)
    try:
        cli.ping()
    except Exception:
        pytest.skip("Redis not reachable at localhost:6379; skipping Redis tests")
    return cli


# ---------------------------------------------------------------------------
# Basic synchronous behavior
# ---------------------------------------------------------------------------
def test_core_basic_set_get_mapping_api():
    """Basic dict-like set/get behavior using the mapping API."""
    d = LiveDict()
    d["k1"] = "hello"
    assert d["k1"] == "hello"


def test_storage_bucket_behavior_with_bucketed_preset():
    """
    Verify bucketed preset behavior:
    - preset 'bucketed' must create a LiveDict with bucket support
    - set/get with explicit bucket name must succeed
    """
    d = LiveDictPresetBuilder("bucketed").build()
    assert isinstance(d.config.common.default_ttl, int)
    d.set("alice", {"name": "Alice"}, bucket="users", ttl=5)
    v = d.get("alice", bucket="users")
    assert isinstance(v, dict) and v["name"] == "Alice"


# ---------------------------------------------------------------------------
# Persistence tests (SQLite & File)
# ---------------------------------------------------------------------------
def test_persistence_sqlite_backend_mirror_shared_cipher():
    """
    Test that values persisted into the SQLite backend with encryption can be
    read back by a fresh LiveDict instance when both instances share the same cipher.

    Steps:
        - Build a LiveDict configured with an SQLite backend
        - Use a shared CipherAdapter to ensure decryptability across instances
        - Write (persist=True) then create a new LiveDict and read via backend
    """
    builder = (
        LiveDictFluentBuilder()
        .preset("durable_sql")
        .with_sql(dsn=f"sqlite:///{SQL_DB_PATH}")
        .bucket_policy(default_bucket="main", per_key=False)
        .with_defaults()
    )
    cfg = builder.preview()

    # first instance writes (using shared cipher)
    d = LiveDict.from_config(cfg, cipher=_SHARED_TEST_CIPHER)
    key = "persist_me"
    val = {"x": 123}
    d.set(key, val, backend="sql", persist=True, ttl=60)
    # stop the first instance to mimic a clean shutdown
    d.stop()

    # create a fresh instance which uses the same shared cipher and read back
    cfg2 = LiveDictConfig.model_validate(cfg.model_dump())
    d2 = LiveDict.from_config(cfg2, cipher=_SHARED_TEST_CIPHER)
    try:
        read = d2.get(key, backend="sql")
        assert read == val
    finally:
        d2.stop()


def test_file_backend_persistence_and_encryption_storage():
    """
    Validate that FileBackend receives a persisted (encrypted) blob when persist=True.

    This test asserts:
        - FileBackend exists in `d.backends`
        - FileBackend.get returns a (ciphertext, expire_at) tuple
        - ciphertext is bytes and is not raw plaintext JSON
    """
    b = (
        LiveDictFluentBuilder()
        .preset("simple")
        .with_file_backend(FILE_BACKEND_DIR)
        .with_defaults(ttl=120)
    )
    cfg = b.preview()
    d = LiveDict.from_config(cfg)
    key = "file_key"
    val = {"hello": "world"}
    d.set(key, val, backend="file", persist=True, ttl=30)

    file_be = d.backends.get("file")
    assert file_be is not None
    raw = file_be.get("__default__", key)
    assert raw is not None, "FileBackend did not return persisted data"
    ciphertext, expire_at = raw
    assert isinstance(ciphertext, (bytes, bytearray))
    assert b'"hello"' not in ciphertext


# ---------------------------------------------------------------------------
# Builder & config tests (json/yaml/env/interactive)
# ---------------------------------------------------------------------------
def test_json_and_yaml_builders_preview_and_build(tmp_path_factory):
    """Exercise JSON and YAML builders and ensure they produce valid config and LiveDict."""
    json_cfg = {
        "storage": {"inmemory": {"enabled": True, "use_buckets": True}},
        "common": {"default_ttl": 77},
    }
    js_path = os.path.join(TEST_DIR, "livedict_config.json")
    with open(js_path, "w", encoding="utf8") as f:
        json.dump(json_cfg, f)

    jbuilder = LiveDictJSONBuilder(js_path)
    cfg = jbuilder.preview()
    assert cfg.common.default_ttl == 77
    ld = jbuilder.build()
    assert isinstance(ld, LiveDict)

    try:
        import yaml  # type: ignore
    except Exception:
        pytest.skip("PyYAML not installed - skipping YAML builder test")

    yml_path = os.path.join(TEST_DIR, "livedict_config.yml")
    with open(yml_path, "w", encoding="utf8") as f:
        f.write(
            "storage:\n  inmemory:\n    enabled: true\n    use_buckets: false\ncommon:\n  default_ttl: 55\n"
        )
    ybuilder = LiveDictYAMLBuilder(yml_path)
    cfg2 = ybuilder.preview()
    assert cfg2.common.default_ttl == 55
    ld2 = ybuilder.build()
    assert isinstance(ld2, LiveDict)


def test_env_builder_reads_environment(monkeypatch):
    """Env builder should pick up LIVEDICT_* variables and map them to config."""
    monkeypatch.setenv("LIVEDICT_common_default_ttl", "42")
    b = LiveDictEnvBuilder()
    cfg = b.preview()
    assert cfg.common.default_ttl in (42, "42") or cfg.common.default_ttl == 42


def test_interactive_builder_quick_flow(monkeypatch):
    """Non-blocking interactive builder preview using monkeypatched input."""
    inputs = iter(["y", "mybucket", "10"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    b = LiveDictInteractiveBuilder()
    cfg = b.preview()
    assert cfg.storage.inmemory.bucket_policy.default_bucket == "mybucket"


# ---------------------------------------------------------------------------
# TTL, expiry, and limits
# ---------------------------------------------------------------------------
def test_ttl_expiry_and_monitor_removes_entries():
    """Short TTL should expire an entry and cause get() to return None afterwards."""
    d = LiveDict()
    d.set("short", "bye", ttl=1)
    assert d.get("short") == "bye"
    time.sleep(1.3)
    assert d.get("short") is None


def test_limits_raise_memoryerror_when_exceeded():
    """In-memory limits defined in config should raise MemoryError when exceeded."""
    cfg = LiveDictConfig.model_validate(
        {
            "storage": {
                "inmemory": {
                    "enabled": True,
                    "use_buckets": True,
                    "limits": {"max_total_keys": 3, "max_keys_per_bucket": 10},
                }
            },
            "common": {"default_ttl": 600},
        }
    )
    d = LiveDict.from_config(cfg)
    d.set("a", 1, bucket="b1")
    d.set("b", 2, bucket="b1")
    d.set("c", 3, bucket="b1")
    with pytest.raises(MemoryError):
        d.set("d", 4, bucket="b1")


# ---------------------------------------------------------------------------
# Listener / hooks tests (sync + async)
# ---------------------------------------------------------------------------
def test_listener_called_on_set_sync():
    """Global listeners added via add_listener should be invoked synchronously on set()."""
    rec: list = []
    d = LiveDict()

    def ln(k: str, v: Any):
        rec.append((k, v))

    d.add_listener(ln)
    d.set("lkey", 99)
    assert any(item[1] == 99 for item in rec)


@pytest.mark.asyncio
async def test_async_set_get_delete_wrappers_and_listener():
    """Async wrapper should correctly proxy to sync LiveDict and maintain behavior."""
    ad = AsyncLiveDict()
    called: list = []

    def ln(k: str, v: Any):
        called.append((k, v))

    # register on underlying sync LiveDict
    ad._ld.add_listener(ln)
    await ad.set("akey", "av")
    val = await ad.get("akey")
    assert val == "av"
    await ad.delete("akey")
    assert (await ad.get("akey")) is None
    assert any(item[1] == "av" for item in called)


# ---------------------------------------------------------------------------
# Redis (optional)
# ---------------------------------------------------------------------------
def test_bulk_set_get_with_redis_if_available():
    """Bulk persist to Redis backend if Redis is available; otherwise skip."""
    try:
        import redis  # type: ignore
    except Exception:
        pytest.skip("redis not installed")
    try:
        rc = redis.Redis(host="localhost", port=6379)
        rc.ping()
    except Exception:
        pytest.skip("redis not reachable at localhost:6379")

    d = LiveDict()

    rbackend = RedisBackend(url="redis://localhost:6379")
    d.backends["redis_test"] = rbackend
    total = 200
    for i in range(total):
        k = f"rkey_{i}"
        v = f"rv_{i}"
        d.set(k, v, backend="redis_test", persist=True, ttl=60)
        if i % 50 == 0:
            print("   set", i)
    # verify a few
    for i in (0, 50, 199):
        k = f"rkey_{i}"
        assert d.get(k, backend="redis_test") == f"rv_{i}"


# ---------------------------------------------------------------------------
# Uncomment the function below to enable cleanup of test artifacts
# ---------------------------------------------------------------------------

# def test_cleanup_artifacts():
#     """Remove files and folders created by this suite (best-effort)."""
#     if os.path.isdir(FILE_BACKEND_DIR):
#         try:
#             shutil.rmtree(FILE_BACKEND_DIR)
#         except Exception as e:
#             print("cleanup: failed to remove file backend dir:", e)
#     for p in (JSON_CFG_PATH, YAML_CFG_PATH, SQL_DB_PATH):
#         if os.path.exists(p):
#             try:
#                 os.remove(p)
#             except Exception as e:
#                 print("cleanup: failed to remove", p, ":", e)
#     assert True
