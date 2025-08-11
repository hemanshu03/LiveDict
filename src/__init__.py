# src/livedict/core.py
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

from .core import *

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