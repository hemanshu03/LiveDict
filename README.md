# LiveDict (Release v1.0.0)

**Encrypted, TTL-based, Persistent Python Dictionary with Hook Callbacks**

LiveDict is a secure, extensible, and ephemeral key-value store designed for applications that need in-memory caching with optional persistence and encryption.

## Highlights
* AES-GCM encryption (via `cryptography`) with a deterministic fallback for test environments.
* TTL expiry driven by a heap-based monitor thread for efficient scheduling.
* Optional persistence backends:
  - SQLite (file-backed DB)
  - File-backed object store (per-bucket files)
  - Redis (thin wrapper; requires `redis` package)
* Hook callbacks (`on_access`, `on_expire`) executed safely (sandboxing recommended).
* Pydantic-backed configuration models for clarity and validation.
* Bucket policies and limits to control memory usage and namespaces.

---

## Installation

Minimum supported Python: 3.8+

Install core dependencies:
```bash
pip install pydantic cryptography redis typing-extensions
```

If you prefer to install via setup.py:
```bash
pip install .
```

---

## Quick Start

```python
from src.livedict.core import LiveDict, LiveDictConfig, SQLiteBackend, CipherAdapter

# Create a sqlite backend and pass to LiveDict for persistence
db = SQLiteBackend(dsn="sqlite:///livedict.db")
cfg = LiveDictConfig()

store = LiveDict(config=cfg, cipher=CipherAdapter(), backends={"sqlite": db})

store.set("username", "alice", ttl=60)
print(store.get("username"))  # -> 'alice'

store.stop()  # stop the monitor thread cleanly
```

---

## Features & Notes

### Encryption
* Uses AES-GCM when `cryptography` is available.
* Fallback deterministic XOR + base64 if cryptography absent (useful for tests).
* Keep the same CipherAdapter (or same keys) across restarts to decrypt persisted blobs.

### Persistence Backends
* SQLiteBackend uses short-lived connections and has an any-bucket fallback lookup.
* FileBackend stores entries as per-bucket small files with JSON metadata.
* RedisBackend is a thin wrapper — `redis-py` required for full functionality.

### Configuration & Limits
* Use pydantic `LiveDictConfig` to tune defaults, monitor behavior, and backend settings.
* Memory limits and heap rebuild thresholds help avoid large memory usage.

---

## Documentation
See the [docs](https://github.com/hemanshu03/LiveDictDocumentations/blob/1e93dbb91c8d4488a8fb9284974e82d23a2bd3a1/APIv1-0-0-release.md).

## Contributing
PRs and issues welcome. Please follow the repo's contribution and code style guidelines.

## License
MIT License
