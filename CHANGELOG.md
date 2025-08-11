# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows Semantic Versioning.

## Release: [v1.0.0] - 2025-08-11

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
* Packaging bumped to `1.0.0-release` to mark the release-ready core implementation.
* README and packaging metadata updated to reflect new dependencies and features.

### Fixed
* Backend expiry handling improved to avoid stale reads.
* sqlite backend uses short-lived sqlite3 connections to avoid file locks on Windows.
* File backend tolerant lookup fixes and safer cleanup logic.

---

## Prior patch notes (v1.0.1 and earlier)
See previous entries for historical or experimental changes.
