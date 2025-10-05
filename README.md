# LiveDict (Release v2.0.2)

**TTL-based, Persistent / Ephemeral Python Dictionary with Hook Callbacks and Sandbox**

LiveDict is a flexible, sandbox-aware, dictionary-like key-value store that supports both **synchronous** and **asynchronous** modes, **TTL-based expiry**, and **multiple backends** (memory, SQLite, Redis).

---

## 🔧 Highlights

* **Callbacks fixed:** no more duplicate callback executions (v2.0.2).
* **Sandbox active:** callbacks execute safely in isolated environments.
* **Cryptography removed:** users must now handle encryption externally.
* **Google-style docstrings:** comprehensive across all modules.
* **Multiple backends:** in-memory, SQLite, and Redis supported.
* **Per-key locks:** ensure safe concurrent access.
* **Fully async/sync support** with unified API design.

---

## 📦 Installation

**Python 3.8+ required**

```bash
pip install livedict
```

---

## 🧠 Overview

LiveDict provides a **dictionary-like interface** in Python with TTL expiry, callback hooks, sandboxing, and optional persistence. It can function as a **cache**, **runtime state manager**, or **ephemeral store** in both synchronous and asynchronous environments.

| Feature   | Description                                           |
| --------- | ----------------------------------------------------- |
| TTL       | Key expiry with background cleanup                    |
| Callbacks | Triggered on set, access, expire                      |
| Sandbox   | Prevents faulty/slow callbacks from halting execution |
| Locking   | Per-key locking for concurrency safety                |
| Backends  | Memory, SQLite, Redis                                 |

---

## ⚡ Quick Usage

### Synchronous Example

```python
from livedict import LiveDict

live = LiveDict(work_mode='sync', backend='memory')
live.set('foo', 123)
print(live.get('foo'))  # 123
```

---

### Asynchronous Example

```python
import asyncio
from livedict import LiveDict

async def main():
    live = LiveDict(work_mode='async', backend='memory')
    await live.set('bar', 'hello')
    print(await live.get('bar'))

asyncio.run(main())
```

---

### TTL / Expiry

```python
import time
from livedict import LiveDict

live = LiveDict(work_mode='sync', backend='memory')
live.set('temp', 'expire-me', ttl=2)
print(live.get('temp'))  # 'expire-me'
time.sleep(3)
print(live.get('temp'))  # None (expired)
```

---

### Callbacks (v2.0.2-fixed)

```python
def on_set(key, val):
    print(f"Set {key} = {val}")

async def on_expire(key, val):
    print(f"{key} expired")

live = LiveDict(work_mode='sync', backend='memory')
cb1 = live.register_callback('set', on_set)
cb2 = live.register_callback('expire', on_expire, is_async=True)

live.set('foo', 42)
```

*Disable or remove callbacks easily:*

```python
live.set_callback_enabled(cb1, False)
live.unregister_callback(cb2)
```

> **v2.0.2 Note:** Fixed a bug where callbacks were executed twice due to redundant handling in `_trigger_event`.

---

### Sandbox Execution

```python
import time
from livedict import LiveDict

def slow_callback(key, val):
    time.sleep(3)  # Timeout example

def bad_callback(key, val):
    raise RuntimeError("Oops!")

live = LiveDict(work_mode='sync', backend='memory')
live.register_callback('set', slow_callback, timeout=1.0)
live.register_callback('set', bad_callback)

live.set('x', 99)  # Sandbox isolates exceptions/timeouts
```

---

### Locking Example

```python
from livedict import LiveDict

live = LiveDict(work_mode='sync', backend='memory')
live.set('counter', 1)

if live.lock('counter', timeout=1):
    try:
        value = live.get('counter')
        live.set('counter', value + 1)
    finally:
        live.unlock('counter')

print(live.get('counter'))  # Updated safely
```

---

## 🧩 Backends

| Backend | Mode       | Description                   |
| ------- | ---------- | ----------------------------- |
| memory  | sync/async | Ephemeral, in-memory store    |
| SQLite  | sync/async | File-backed persistence       |
| Redis   | sync/async | Requires running Redis server |

---

## 🧪 Example Demonstrations

See the repository examples:

* [`test_sync.py`](https://github.com/hemanshu03/LiveDict/blob/main/test_sync.py)
* [`test_async.py`](https://github.com/hemanshu03/LiveDict/blob/main/test_async.py)

These demonstrate TTL, callbacks, sandbox safety, locking, and async concurrency.

---

## 🧾 Changelog

### Release: [2.0.2] - 2025-10-05 — latest

**Changed**

* Fixed callback duplication caused by redundant async loop in `_trigger_event`.

### Release: [2.0.1] - 2025-10-05

**Changed**

* Removed `sqlite3` dependency from `setup.py`. (It’s built-in since Python 3.6+.)

### Release: [2.0.0] - 2025-10-04

**Added**

* Full Google-style docstrings.
* Sandbox module is now active and maintained.

**Changed**

* Version bump to `2.0.0`.
* Packaging updated for PyPI.

**Removed**

* Cryptography and encryption modules removed — users must now handle encryption externally.

**Notes**

* Sandbox behavior is live; users should review sandbox performance and limitations in their environment.

---

## 🧱 Contributing

* Use **Google-style docstrings** for all functions, classes, and modules.
* Generate documentation using `pdoc` or Sphinx with the napoleon extension.
* Report issues and PRs on GitHub.

---

## ⚖️ License

MIT License © 2025 LiveDict
[![GitHub license](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/hemanshu03/LiveDict/blob/main/LICENSE)

> **LiveDict** — TTL-based Python key-value store by [hemanshu03](https://github.com/hemanshu03)

---

## ❤️ Support Development

If you find LiveDict useful, consider supporting the project:
👉 [LiveDict on GitHub](https://github.com/hemanshu03/LiveDict)

---

