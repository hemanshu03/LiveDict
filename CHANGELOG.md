# Changelog

All notable changes to this project will be documented in this file.  
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2025-08-05

### Added
- **Core LiveDict implementation**
  - Encrypted in-memory key-value store using AES-256-GCM.
  - Per-key and default TTL (time-to-live) support.
  - Automatic expiry management with background monitoring thread.

- **Hooks System**
  - Access hooks: executed on key retrieval.
  - Expiry hooks: executed on key expiration.
  - Sandboxed execution with configurable timeouts and memory limits.

- **Redis Integration**
  - Optional persistence and distributed storage via `redis-py`.
  - TTL synchronization with Redis expiration system.

- **Security**
  - AES-GCM encryption with auto-generated or custom keys.
  - Isolation of hooks to prevent blocking or crashes in the main process.

- **Thread Safety**
  - Concurrent-safe `set`, `get`, and `delete` using locks and condition variables.

- **Cross-Platform Support**
  - Works on Linux, macOS, and Windows (with Windows-specific sandbox limitations).

- **Documentation**
  - Comprehensive inline docstrings for public API.
  - Sphinx documentation templates in `docs/`.
  - `README.md` with usage examples and installation instructions.

- **Packaging**
  - `pyproject.toml` and `setup.py` for modern packaging and PyPI publishing.
  - `tests/` directory with `pytest`-based test suite.

---

## [Unreleased]

### Planned
- Pluggable storage backends (SQLite, file-based).
- Metrics/observability for hook executions and TTL events.
- Windows-compatible memory limit enforcement.
- Async/await API for asyncio-based applications.

---

### Notes
- **Windows Limitations:**
  - Hooks must be defined at module top-level (due to `multiprocessing.spawn` pickling).
  - Memory-limiting for sandboxing is currently unsupported; timeout enforcement still applies.
