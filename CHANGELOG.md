# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2025-10-04
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
