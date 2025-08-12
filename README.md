# LiveDict (Release v1.0.4)

**Encrypted, TTL-based, Persistent Python Dictionary with Hook Callbacks**

LiveDict is a secure, extensible, and ephemeral key-value store designed for applications that need in-memory caching with optional persistence and encryption.

## License
MIT License. © 2025 LiveDict. All rights reserved.

[![GitHub license](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/hemanshu03/LiveDict/blob/main/LICENSE)

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

Install with:
```bash
pip install livedict
```

---

## Quick Start

```python
from livedict import LiveDict, LiveDictConfig, SQLiteBackend, CipherAdapter

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
See:
  - [Documentation/s](https://github.com/hemanshu03/LiveDictDocumentations/blob/1e93dbb91c8d4488a8fb9284974e82d23a2bd3a1/LD1-0-4-release.md).
  - [Documentation/s and more on Website](https://livedict.pages.dev/)

---

# About License:
### SPDX-License-Identifier: MIT
### Copyright (c) 2025 Hemanshu

---

# If you want to credit LiveDict in your docs/acknowledgements, this short line works:
LiveDict - Encrypted TTL-based Python key-value store by [hemanshu03](https://github.com/hemanshu03). Find LiveDict on GitHub @[LiveDict](https://github.com/hemanshu03/LiveDict)

---

# Contributing to LiveDict

Thanks for thinking about contributing! Please:

* Open an issue first to discuss bigger changes.
* Fork the repo, create a feature branch, submit with tests and docs.
* Keep backward compatibility in mind; bump major/minor in `CHANGELOG.md` if needed.

---

If you find LiveDict useful and want to support continued development, consider sponsoring the project: https://github.com/sponsors/hemanshu03
=======

# About License:
### SPDX-License-Identifier: MIT
### Copyright (c) 2025 Hemanshu

---

# If you want to credit LiveDict in your docs/acknowledgements, this short line works:
LiveDict - Encrypted TTL-based Python key-value store by [hemanshu03](https://github.com/hemanshu03). Find LiveDict on GitHub @[LiveDict](https://github.com/hemanshu03/LiveDict)

---

# Contributing to LiveDict

Thanks for thinking about contributing! Please:

* Open an issue first to discuss bigger changes.
* Fork the repo, create a feature branch, submit with tests and docs.
* Keep backward compatibility in mind; bump major/minor in `CHANGELOG.md` if needed.

---

If you find LiveDict useful and want to support continued development, consider sponsoring the project: https://github.com/sponsors/hemanshu03

