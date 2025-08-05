# LiveDict

Encrypted, TTL-based in-memory dictionary with optional Redis persistence and sandboxed hooks.

## Features

- AES-256-GCM encryption for all stored data
- Automatic key expiry with background monitoring
- Hooks on access/expire, executed in sandboxed subprocesses
- Thread-safe design
- Optional Redis support for cross-process storage

## Installation

PyPI (Yet to be launched here..):
```bash
pip install ... (livedict)
```

TestPyPI (Is available here):
```bash
pip install -i https://test.pypi.org/simple/ livedict==1.0.0
```
