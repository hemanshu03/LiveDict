# LiveDict (Release v1.0.4)

**TTL-based, (optionally) Persistent Python Dictionary with Hook Callbacks**

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

# LiveDict (Release v2.0.0)

LiveDict is a small utility library providing in-memory dictionary-like structures with
synchronous and asynchronous variants, a sandbox module, and flexible storage backends.

**Important changes in v2**
- Cryptography removed: the package no longer performs encryption. Users must provide their own cryptographic handling.
- Sandbox is active: behaves as implemented in `livedict/modules/sandbox.py`.

## Sandbox usage

Review `livedict/modules/sandbox.py` for details. The sandbox module is included and active;
exercise caution and review its behavior before running untrusted code.

---

## License
GNU Affero General Public License v3.0 © 2025 Hemanshu Vaidya  
[![GitHub license](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](https://github.com/hemanshu03/LiveDict/blob/main/LICENSE)

## Installation

Minimum supported Python: 3.8+

Install with:
```bash
pip install livedict
```

## Demonstration

Visit [testfile.py](https://github.com/hemanshu03/LiveDict/blob/main/testfile.py) as a demonstration on how to use LiveDict.

---

## Contributing

- Generate documentation using your preferred tools (pdoc, Sphinx with napoleon for Google-style).
- This release uses Google-style docstrings across the codebase.

---

## About License:
  - SPDX-License-Identifier: GNU Affero Public License
  - Copyright (c) 2025 Hemanshu

---

## If you want to credit LiveDict in your docs/acknowledgements, this short line works:
LiveDict - TTL-based Python key-value store by [hemanshu03](https://github.com/hemanshu03). Find LiveDict on GitHub @[LiveDict](https://github.com/hemanshu03/LiveDict)

---

## If you find LiveDict useful and want to support continued development:
Consider sponsoring the project: [LiveDict](https://github.com/hemanshu03/LiveDict)

===
