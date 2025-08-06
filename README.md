
---

# LiveDict

# Encrypted, TTL-based, Persistent Python Dictionary with Hook Callbacks

## Overview

**LiveDict** is a secure, extensible, and ephemeral key-value store designed for applications that need in-memory caching with optional Redis persistence, AES-GCM encryption, automatic TTL expiry, and event hooks.

Key features include:

* **Encryption**: AES-GCM with support for multiple keys and key rotation.
* **TTL Expiry**: Heap-based scheduler removes expired keys efficiently.
* **Hook Callbacks**: `on_access` and `on_expire` executed in a sandbox.
* **Redis Persistence**: Optional cross-process/store persistence with fallback.
* **Serialization**: JSON (default) or msgpack support.
* **Access Control**: Optional `auth_func` for per-operation authorization.

Ideal for secure session caches, ephemeral storage, or encrypted config stores.

---

## Installation

### Basic Install


PyPI (Yet to be launched here..):
```bash
pip install ... (livedict)
```

TestPyPI (Is available here):
```bash
pip install -i https://test.pypi.org/simple/livedict==1.0.1
```

### With msgpack Support

```bash
pip install msgpack
```

### With Redis Support

```bash
pip install redis
```

---

## Quick Start

```python
from livedict import LiveDict
import time

# Initialize store with default TTL of 5 seconds
store = LiveDict(default_ttl=5)

# Set and retrieve a value
store.set("username", "alice")
print(store.get("username"))  # Output: 'alice'

# Wait for TTL to expire
time.sleep(6)
print(store.get("username"))  # Output: None

# Stop the background expiry monitor
store.stop()
```

---

## Features

### 1. AES-GCM Encryption

* Each value is encrypted before storage.
* Nonces are randomly generated per entry.
* Supports multiple keys for decryption and seamless key rotation.

### 2. TTL Expiry with Heap Monitor

* Uses `heapq` to efficiently track upcoming expirations.
* Background thread automatically removes expired keys.

### 3. Hook Callbacks

* `on_access(key, value)`: Triggered when a value is retrieved.
* `on_expire(key)`: Triggered when a value expires.
* Executed in a sandbox with timeout and memory constraints.

Example:

```python
def accessed(key, value):
    print(f"Accessed {key} -> {value}")

def expired(key):
    print(f"{key} expired!")

store.set("session", "active", ttl=2, on_access=accessed, on_expire=expired)
print(store.get("session"))  # triggers on_access
time.sleep(3)                # triggers on_expire
```

### 4. Redis Persistence (Optional)

Integrate with Redis for persistence and sharing between processes.

```python
import redis
client = redis.StrictRedis()

store = LiveDict(redis_client=client, enable_redis=True)
store.set("config", {"mode": "secure"})
print(store.get("config"))
```

### 5. Key Rotation

Rotate encryption keys without downtime:

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
new_key = AESGCM.generate_key(256)
store.rotate_key(new_key)
```

Old keys remain available for decryption; new entries use the latest key.

### 6. Access Control

Restrict operations with a custom `auth_func`:

```python
def acl(operation, key):
    # Example: only allow 'get' operations
    return operation == "get"

store = LiveDict(auth_func=acl)
store.set("secret", "value")  # raises PermissionError
```

---

## Advanced Usage

### JSON vs msgpack

* JSON: human-readable, built-in.
* msgpack: compact binary format, faster serialization (requires `msgpack` library).

### Sandbox Hook Runner

* Hooks run in subprocess (Unix) or threads (Windows).
* Configurable timeout (default 1s) and memory limit (default 50MB on Unix).
* Prevents hooks from blocking main process or consuming excessive resources.

### Internals

* Entries stored in `_store` dict with expiration tracked in `_heap` (min-heap).
* Background thread `_monitor` checks for expired keys and triggers `on_expire`.
* Encryption keys stored in `_keys` list; decryption attempts from newest to oldest.

---

## Security Notes

* AES-GCM provides authenticated encryption (integrity + confidentiality).
* Nonces are generated randomly; ensure system has a strong entropy source.
* Key rotation is additive: new key is appended, old keys remain for decryption.
* For maximum security, periodically drop oldest keys and re-encrypt data.

---

## Performance Tips

* Use JSON for simplicity, msgpack for high-performance binary serialization.
* Enable Redis for horizontal scaling or process restarts.
* Minimize long-running callbacks; hook runner enforces timeout.

---

## API Reference

### `LiveDict`

#### `__init__(...)`

Initialize the store.

Parameters:

* `default_ttl` (int): Default TTL in seconds.
* `auth_func` (callable): Access control function `(operation, key) -> bool`.
* `serializer` (str): `'json'` or `'msgpack'`.
* `encryption_keys` (list\[bytes]): Pre-existing AES keys.
* `redis_client`: Redis client instance.
* `enable_redis` (bool): Enable Redis persistence.

#### `set(key, value, ttl=None, on_access=None, on_expire=None)`

Encrypt and store value with optional TTL and hooks.

#### `get(key)`

Retrieve decrypted value; triggers `on_access` hook.

#### `delete(key)`

Remove key from memory and Redis (if enabled).

#### `rotate_key(new_key)`

Add a new AES key for future encryptions.

#### `stop()`

Stop background expiry monitor.

---

## License

MIT License

---

# Thinking of a new Features

## **Goals**

1. **Full async API**:

   * `async def aset()`, `async def aget()`, `async def adelete()`, `async def arotate_key()`, etc.
   * Async-safe expiry monitor using `asyncio.Task` instead of threads.

2. **Preserve sync API** (no breaking changes).

3. **Async Redis support**:

   * Use [`aioredis`](https://aioredis.readthedocs.io/) or `redis.asyncio` (new in redis-py 4.x).
   * Automatically select async or sync backend depending on method used.

4. **Hook execution**:

   * Support both sync and async hooks (detect `iscoroutinefunction`).
   * Async hooks executed in async tasks with timeout.

5. **Common codebase**:

   * Core logic shared, minimal duplication.
   * Serialization/encryption code reused by both modes.

---

## **High-level design**

### 1. Dual Base Classes

* **`BaseLiveDict`**: shared encryption, serialization, key rotation.
* **`LiveDict`**: sync version (current implementation).
* **`AsyncLiveDict`**: async version (using `asyncio.Lock`, `asyncio.Condition`, and async Redis).

### 2. Async Redis

* Use `redis.asyncio.StrictRedis` (built-in to `redis>=4.2`).
* Connect via `await redis.from_url(...)`.

### 3. Async expiry monitor

* Replace thread with `asyncio.create_task(self._monitor())`.
* Use `asyncio.sleep(timeout)` instead of condition waits.

### 4. Sandbox runner

* For async, we can:

  * Use **`asyncio.wait_for`** with subprocess for isolation OR
  * Provide **async hook execution** with timeout directly (less isolation but consistent).
* Could keep process isolation only for sync version to avoid heavy complexity.

---

## **API Proposal**

```python
# Sync usage (unchanged)
ld = LiveDict()
ld.set("key", {"val": 1})
ld.get("key")

# Async usage
ald = await AsyncLiveDict.create(redis_url="redis://localhost:6379/0")

await ald.aset("key", {"val": 1})
val = await ald.aget("key")
```

---

## **Migration Plan**

* Add `AsyncLiveDict` in parallel to `LiveDict` (non-breaking).
* Gradually refactor shared logic (encryption, serialization) into `BaseLiveDict`.
* Mark async API as **experimental** in docs first.

---

## **Dependencies**

* `redis>=4.2` (already there, supports `redis.asyncio`).
* No extra deps (asyncio is stdlib).

---
