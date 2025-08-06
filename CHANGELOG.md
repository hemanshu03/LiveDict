# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Patch Update for LiveDict: [v1.0.1] - 2025-08-06

### Added

* **Comprehensive README.md**

  * Detailed usage instructions, quick start, and advanced examples.
  * Security notes, performance tips, and API reference.
  * Installation guidance for optional features (`msgpack`, `redis`).

### Changed

* **_Expiry management:_** Migrated expiry tracking to **_heap queue (priority queue)_** for faster lookups and improved performance under heavy load.

* **_Enhanced LiveDict docstring:_** Added **_Quick Start_** and richer examples, matching the style of Python standard library docs.

* **_Improved inline documentation:_** Standardized parameter and return annotations for clarity.

* **_Redis handling fix:_** `get()` now gracefully handles invalid/foreign Redis values by returning None instead of raising decryption errors.

* **_Sandbox hook timeout behavior:_** **_SandboxTimeout now properly propagates_** during on_access hook execution. **_Other hook errors are logged_** but do not interrupt normal operations.

* **_Thread stability:_** Minor locking improvements to avoid missed wakeups during expiry checks.

---

