# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows Semantic Versioning.

## Release: [2.0.2] - 2025-10-05 - latest
### Changed
- The callback handler was calling the callbacks 2 times.I messed up by adding another loop if there is any RunTimeError at _run_async in the _trigger_event function.. fixed it.

## Release: [2.0.1] - 2025-10-05
### Changed
- setup.py had a major requirement issue that was fixed. (I had mistakenly added sqlite3 as a requirement but it's not needed since Python 3.6+ has included it.)

## Release: [2.0.0] - 2025-10-04
### Added
- Comprehensive Google-style docstrings added to modules, classes, and functions.
- Sandbox functionality is now active and maintained within the package.

### Changed
- Project version bumped to `2.0.0`.
- Packaging files (`setup.py`, `pyproject.toml`) updated for PyPI release.

### Removed
- Cryptography-related code has been removed from the package. Encryption and cryptographic responsibilities are now delegated to the user; the library no longer provides built-in cryptographic primitives.

### Notes
- The `sandbox` module is live and behaves according to the code in this release; users should review sandbox behavior for their environment and use cases.

## Release: [v1.0.4] - 2025-08-11

### Added
* Pydantic-based configuration models for storage/backends/monitoring and bucket policies.
* New persistence backends:
  - SQLite backend with short-lived connections and indexing.
  - File-backed object store for external object storage emulation.
  - Improved InMemory backend used for testing and simple runs.
* CipherAdapter with AES-GCM (cryptography) and deterministic base64 XOR fallback.
* Heap-based expiry monitor with efficient wake-ups and rebuild heuristics.
* Bucket semantics, bucket policies, and hybrid routing placeholders.
* Better backend fallbacks and tolerant lookup behavior (any-bucket fallback for SQLite/File).
* Expanded API and documentation covering rotation, hooks, and persistence options.

### Changed
* Packaging bumped to `1.0.4-release` to mark the release-ready core implementation.
* README and packaging metadata updated to reflect new dependencies and features.

### Fixed
* Backend expiry handling improved to avoid stale reads.
* sqlite backend uses short-lived sqlite3 connections to avoid file locks on Windows.
* File backend tolerant lookup fixes and safer cleanup logic.

---
## Prior patch notes (v1.0.4 and earlier)
No previous changes. This is the first version of LiveDict's official release.

