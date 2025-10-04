"""livedict.py — LiveDict v2 module.

Module contains implementations for LiveDict core components."""
import threading
import time
import heapq
import uuid
import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, List, Tuple
from .sandbox import sandbox_wrap_sync, sandbox_wrap_async
from .exceptions import LockedKeyError, SandboxError, LiveDictError
from .storage_backend import MemoryBackend, SQLiteBackend, RedisBackend
_EVENT_SET = 'set'
_EVENT_GET = 'get'
_EVENT_DELETE = 'delete'
_EVENT_EXPIRE = 'expire'

@dataclass
class CallbackEntry:
    """CallbackEntry."""
    'CallbackEntry class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = CallbackEntry()'
    id: str
    fn: Callable
    timeout: Optional[float] = 2.0
    enabled: bool = True
    is_async: bool = False

class ExpiryScheduler(threading.Thread):
    """ExpiryScheduler.

        Internal scheduler used to track keys with TTL and call the expiry handler
        when items expire.
"""
    'ExpiryScheduler class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = ExpiryScheduler()'

    def __init__(self):
        super().__init__(daemon=True, name='LiveDict-ExpiryScheduler')
        self._heap: List[Tuple[float, str]] = []
        self._cancelled = set()
        self._cv = threading.Condition()
        self._stop = False
        self._on_expire = None

    def schedule(self, key: str, when: float):
        """schedule."""
        'schedule.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    when (typing.Any): Description of `when`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._cv:
            heapq.heappush(self._heap, (when, key))
            self._cv.notify()

    def cancel(self, key: str):
        """cancel."""
        'cancel.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._cv:
            self._cancelled.add(key)
            self._cv.notify()

    def run(self):
        """run."""
        'run.\n\nReturns:\n    typing.Any: Description of return value.'
        while True:
            with self._cv:
                if self._stop:
                    return
                if not self._heap:
                    self._cv.wait()
                    continue
                when, key = self._heap[0]
                now = time.time()
                wait = when - now
                if wait > 0:
                    self._cv.wait(timeout=wait)
                    continue
                heapq.heappop(self._heap)
            if key in self._cancelled:
                with self._cv:
                    self._cancelled.discard(key)
                continue
            if self._on_expire:
                try:
                    self._on_expire(key)
                except Exception:
                    pass

    def stop(self):
        """stop."""
        'stop.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._cv:
            self._stop = True
            self._cv.notify()

class LiveDictImpl:
    """LiveDictImpl."""
    'LiveDictImpl class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = LiveDictImpl()'

    def __init__(self, prevent_race_condition: bool=True, sandbox: bool=True, backend: object='memory'):
        self._sandbox = bool(sandbox)
        if isinstance(backend, str):
            backend = backend.lower()
            if backend in ('memory', None):
                self._backend = MemoryBackend()
            elif backend in ('sqlite', 'sqlite3'):
                self._backend = SQLiteBackend()
            elif backend in ('redis',):
                self._backend = RedisBackend()
            else:
                raise ValueError('unknown backend')
        else:
            self._backend = backend
        self._global_lock = threading.RLock() if prevent_race_condition else _DummyContext()
        self._key_locks: Dict[str, threading.RLock] = {}
        self._key_locks_lock = threading.Lock()
        self._callbacks: Dict[str, Dict[str, List[CallbackEntry]]] = {_EVENT_SET: {}, _EVENT_GET: {}, _EVENT_DELETE: {}, _EVENT_EXPIRE: {}}
        from concurrent.futures import ThreadPoolExecutor
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix='LiveDict-cb')
        self._scheduler = ExpiryScheduler()
        self._scheduler._on_expire = self._handle_expiry
        self._scheduler.start()

    def _get_lock_for_key(self, key: str) -> threading.RLock:
        """_get_lock_for_key."""
        '_get_lock_for_key.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._key_locks_lock:
            lk = self._key_locks.get(key)
            if lk is None:
                lk = threading.RLock()
                self._key_locks[key] = lk
            return lk

    def lock(self, key: str, timeout: Optional[float]=None) -> bool:
        """lock.

        Acquire/Release a lock for a specific key to prevent concurrent modification.

        Args:
            key (str): Key to lock/unlock.
            timeout (Optional[float]): Maximum time to wait when acquiring a lock.

        Raises:
            LockedKeyError: If the key cannot be locked within timeout.
"""
        'lock.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    timeout (typing.Any): Description of `timeout`.\n\nReturns:\n    typing.Any: Description of return value.'
        lk = self._get_lock_for_key(key)
        if timeout is None:
            return lk.acquire()
        return lk.acquire(timeout=timeout)

    def unlock(self, key: str):
        """unlock.

        Acquire/Release a lock for a specific key to prevent concurrent modification.

        Args:
            key (str): Key to lock/unlock.
            timeout (Optional[float]): Maximum time to wait when acquiring a lock.

        Raises:
            LockedKeyError: If the key cannot be locked within timeout.
"""
        'unlock.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        lk = self._get_lock_for_key(key)
        try:
            lk.release()
        except RuntimeError:
            pass

    def set(self, key: str, value: Any, ttl: Optional[float]=None):
        """set.

        Store a value for the specified key.

        Args:
            key (str): Key under which the value will be stored.
            value (typing.Any): Value to store.
            ttl (Optional[float]): Time-to-live in seconds. If provided, the key will be
                automatically removed after `ttl` seconds.

        Returns:
            bool: True if the value was stored successfully.
"""
        'set.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    value (typing.Any): Description of `value`.\n    ttl (typing.Any): Description of `ttl`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._global_lock:
            self._backend.set(key, value, ttl=ttl)
            if ttl is not None:
                when = time.time() + ttl
                self._scheduler.schedule(key, when)
            else:
                self._scheduler.cancel(key)
            self._trigger_event(_EVENT_SET, key, value)

    def get(self, key: str, default: Any=None):
        """get.

        Retrieve a value for the specified key.

        Args:
            key (str): Key to retrieve.
            default (typing.Any): Value to return if key is not present.

        Returns:
            typing.Any: The stored value or `default` if key does not exist.
"""
        'get.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    default (typing.Any): Description of `default`.\n\nReturns:\n    typing.Any: Description of return value.'
        val = self._backend.get(key, default=default)
        if val is not default and val is not None:
            self._trigger_event(_EVENT_GET, key, val)
        return val

    def delete(self, key: str):
        """delete.

        Delete a key from the store.

        Args:
            key (str): Key to delete.

        Returns:
            bool: True if the key existed and was deleted, False otherwise.
"""
        'delete.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._global_lock:
            val = self._backend.get(key, default=None)
            self._backend.delete(key)
            self._scheduler.cancel(key)
            self._trigger_event(_EVENT_DELETE, key, val)

    def items(self):
        """items."""
        'items.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._backend.items()

    def keys(self):
        """keys."""
        'keys.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._backend.keys()

    def exists(self, key: str):
        """exists.

        Check whether a key exists in the store.

        Args:
            key (str): Key to check.

        Returns:
            bool: True if key exists, False otherwise.
"""
        'exists.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._backend.exists(key)

    def _handle_expiry(self, key: str):
        """_handle_expiry."""
        '_handle_expiry.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        try:
            val = self._backend.get(key, default=None)
            self._backend.delete(key)
        except Exception:
            val = None
        self._trigger_event(_EVENT_EXPIRE, key, val)

    def register_callback(self, event: str, fn: Callable, key: Optional[str]=None, timeout: Optional[float]=2.0, is_async: bool=False) -> str:
        """register_callback.

        Manage or trigger event callbacks for LiveDict events (set/get/expire/delete).

        Args:
            *args: See implementation for specific arguments.

        Returns:
            str: Callback id for register, or boolean status for others.
"""
        'register_callback.\n\nArgs:\n    event (typing.Any): Description of `event`.\n    fn (typing.Any): Description of `fn`.\n    key (typing.Any): Description of `key`.\n    timeout (typing.Any): Description of `timeout`.\n    is_async (typing.Any): Description of `is_async`.\n\nReturns:\n    typing.Any: Description of return value.'
        if event not in self._callbacks:
            raise ValueError('invalid event')
        cbid = str(uuid.uuid4())
        entry = CallbackEntry(id=cbid, fn=fn, timeout=timeout, enabled=True, is_async=is_async)
        target = key or '__global__'
        self._callbacks[event].setdefault(target, []).append(entry)
        return cbid

    def unregister_callback(self, cbid: str):
        """unregister_callback.

        Manage or trigger event callbacks for LiveDict events (set/get/expire/delete).

        Args:
            *args: See implementation for specific arguments.

        Returns:
            str: Callback id for register, or boolean status for others.
"""
        'unregister_callback.\n\nArgs:\n    cbid (typing.Any): Description of `cbid`.\n\nReturns:\n    typing.Any: Description of return value.'
        for ev, m in self._callbacks.items():
            for k, lst in list(m.items()):
                new = [e for e in lst if e.id != cbid]
                if new:
                    m[k] = new
                else:
                    m.pop(k, None)

    def set_callback_enabled(self, cbid: str, enabled: bool):
        """set_callback_enabled."""
        'set_callback_enabled.\n\nArgs:\n    cbid (typing.Any): Description of `cbid`.\n    enabled (typing.Any): Description of `enabled`.\n\nReturns:\n    typing.Any: Description of return value.'
        for m in self._callbacks.values():
            for lst in m.values():
                for e in lst:
                    if e.id == cbid:
                        e.enabled = enabled
                        return True
        return False

    def _gather_callbacks(self, event: str, key: str) -> List[CallbackEntry]:
        """_gather_callbacks."""
        '_gather_callbacks.\n\nArgs:\n    event (typing.Any): Description of `event`.\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        res: List[CallbackEntry] = []
        m = self._callbacks.get(event, {})
        if key in m:
            res.extend(m[key])
        if '__global__' in m:
            res.extend(m['__global__'])
        return [e for e in res if e.enabled]

    def _trigger_event(self, event: str, key: str, value: Any):
        """_trigger_event.

        Manage or trigger event callbacks for LiveDict events (set/get/expire/delete).

        Args:
            *args: See implementation for specific arguments.

        Returns:
            str: Callback id for register, or boolean status for others.
"""
        '_trigger_event.\n\nArgs:\n    event (typing.Any): Description of `event`.\n    key (typing.Any): Description of `key`.\n    value (typing.Any): Description of `value`.\n\nReturns:\n    typing.Any: Description of return value.'
        entries = self._gather_callbacks(event, key)
        if not entries:
            return
        for e in entries:
            if self._sandbox:
                if e.is_async:

                    async def _run_async(cbentry: CallbackEntry, val: Any):
                        try:
                            wrapped = sandbox_wrap_async(cbentry.fn, timeout=cbentry.timeout)
                            await wrapped(key, val)
                        except SandboxError:
                            pass
                        except Exception:
                            pass
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(_run_async(e, value))
                    except RuntimeError:

                        def _runner():
                            """_runner.

Returns:
    typing.Any: Description of return value."""
                            loop2 = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop2)
                            try:
                                loop2.run_until_complete(_run_async(e, value))
                            finally:
                                loop2.close()
                        self._executor.submit(_runner)
                else:

                    def _run_sync(cbentry: CallbackEntry, val: Any):
                        """_run_sync.

Args:
    cbentry (typing.Any): Description of `cbentry`.
    val (typing.Any): Description of `val`.

Returns:
    typing.Any: Description of return value."""
                        try:
                            wrapped = sandbox_wrap_sync(cbentry.fn, timeout=cbentry.timeout)
                            wrapped(key, val)
                        except SandboxError:
                            pass
                        except Exception:
                            pass
                    self._executor.submit(_run_sync, e, value)
            elif e.is_async:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(e.fn(key, value))
                except RuntimeError:
                    self._executor.submit(lambda: asyncio.run(e.fn(key, value)))
            else:
                self._executor.submit(e.fn, key, value)

    def stop(self):
        """stop."""
        'stop.\n\nReturns:\n    typing.Any: Description of return value.'
        try:
            self._scheduler.stop()
        except Exception:
            pass
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

class LiveDict:
    """LiveDict.

        Thread-safe dictionary-like container supporting synchronous and asynchronous
        operation modes, key-level locking, TTL-based expiry, event callbacks,
        and pluggable storage backends (in-memory, SQLite, Redis).

        Attributes:
            _backend: Storage backend instance implementing basic get/set/delete.
            _mode (str): 'sync' or 'async' operation mode.
            _scheduler: Expiry scheduler for TTL handling.
"""
    'LiveDict class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = LiveDict()'

    def __init__(self, work_mode: str='sync', backend: str='memory', prevent_race_condition: bool=True, sandbox: bool=True, uri: Optional[str]=None, client: Optional[object]=None):
        work_mode = (work_mode or 'sync').lower()
        if work_mode not in ('sync', 'async'):
            raise ValueError("work_mode must be 'sync' or 'async'")
        self._mode = work_mode
        backend_name = (backend or 'memory').lower()
        if backend_name == 'memory':
            if uri or client:
                print('[LiveDict] INFO: uri/client ignored for memory backend.')
            chosen_backend = MemoryBackend()
        elif backend_name in ('sqlite', 'sqlite3'):
            import sqlite3
            if client is not None:
                if not isinstance(client, sqlite3.Connection):
                    raise TypeError('client must be a sqlite3.Connection for sqlite backend')
                chosen_backend = SQLiteBackend(db_path=':memory:', client=client)
            elif uri is not None:
                chosen_backend = SQLiteBackend(db_path=uri)
            else:
                raise ValueError('SQLite backend requires either uri (db path) or client (sqlite3.Connection).')
        elif backend_name == 'redis':
            try:
                import redis
                from redis import Redis
            except Exception as exc:
                raise RuntimeError('redis library is required for redis backend') from exc
            if client is not None:
                if not isinstance(client, Redis):
                    raise TypeError('client must be a redis.Redis for redis backend')
                chosen_backend = RedisBackend(url=None, client=client)
            elif uri is not None:
                chosen_backend = RedisBackend(url=uri)
            else:
                raise ValueError('Redis backend requires either uri (connection string) or client (redis.Redis).')
        else:
            raise ValueError(f'Unsupported backend: {backend_name}')
        self._impl = LiveDictImpl(prevent_race_condition=prevent_race_condition, sandbox=sandbox, backend=chosen_backend)

    def set(self, key: str, value: Any, ttl: Optional[float]=None):
        """set.

        Store a value for the specified key.

        Args:
            key (str): Key under which the value will be stored.
            value (typing.Any): Value to store.
            ttl (Optional[float]): Time-to-live in seconds. If provided, the key will be
                automatically removed after `ttl` seconds.

        Returns:
            bool: True if the value was stored successfully.
"""
        'set.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    value (typing.Any): Description of `value`.\n    ttl (typing.Any): Description of `ttl`.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.set(key, value, ttl=ttl)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.set(key, value, ttl=ttl))

    def get(self, key: str, default: Any=None):
        """get.

        Retrieve a value for the specified key.

        Args:
            key (str): Key to retrieve.
            default (typing.Any): Value to return if key is not present.

        Returns:
            typing.Any: The stored value or `default` if key does not exist.
"""
        'get.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    default (typing.Any): Description of `default`.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.get(key, default=default)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.get(key, default=default))

    def delete(self, key: str):
        """delete.

        Delete a key from the store.

        Args:
            key (str): Key to delete.

        Returns:
            bool: True if the key existed and was deleted, False otherwise.
"""
        'delete.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.delete(key)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.delete(key))

    def items(self):
        """items."""
        'items.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.items()
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.items())

    def keys(self):
        """keys."""
        'keys.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.keys()
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.keys())

    def exists(self, key: str):
        """exists.

        Check whether a key exists in the store.

        Args:
            key (str): Key to check.

        Returns:
            bool: True if key exists, False otherwise.
"""
        'exists.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.exists(key)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.exists(key))

    def lock(self, key: str, timeout: Optional[float]=None):
        """lock.

        Acquire/Release a lock for a specific key to prevent concurrent modification.

        Args:
            key (str): Key to lock/unlock.
            timeout (Optional[float]): Maximum time to wait when acquiring a lock.

        Raises:
            LockedKeyError: If the key cannot be locked within timeout.
"""
        'lock.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    timeout (typing.Any): Description of `timeout`.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.lock(key, timeout=timeout)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.lock(key, timeout=timeout))

    def unlock(self, key: str):
        """unlock.

        Acquire/Release a lock for a specific key to prevent concurrent modification.

        Args:
            key (str): Key to lock/unlock.
            timeout (Optional[float]): Maximum time to wait when acquiring a lock.

        Raises:
            LockedKeyError: If the key cannot be locked within timeout.
"""
        'unlock.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        if self._mode == 'sync':
            return self._impl.unlock(key)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: self._impl.unlock(key))

    def register_callback(self, event: str, fn: Callable, key: Optional[str]=None, timeout: Optional[float]=2.0, is_async: bool=False) -> str:
        """register_callback.

        Manage or trigger event callbacks for LiveDict events (set/get/expire/delete).

        Args:
            *args: See implementation for specific arguments.

        Returns:
            str: Callback id for register, or boolean status for others.
"""
        'register_callback.\n\nArgs:\n    event (typing.Any): Description of `event`.\n    fn (typing.Any): Description of `fn`.\n    key (typing.Any): Description of `key`.\n    timeout (typing.Any): Description of `timeout`.\n    is_async (typing.Any): Description of `is_async`.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._impl.register_callback(event, fn, key=key, timeout=timeout, is_async=is_async)

    def unregister_callback(self, cbid: str):
        """unregister_callback.

        Manage or trigger event callbacks for LiveDict events (set/get/expire/delete).

        Args:
            *args: See implementation for specific arguments.

        Returns:
            str: Callback id for register, or boolean status for others.
"""
        'unregister_callback.\n\nArgs:\n    cbid (typing.Any): Description of `cbid`.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._impl.unregister_callback(cbid)

    def set_callback_enabled(self, cbid: str, enabled: bool):
        """set_callback_enabled."""
        'set_callback_enabled.\n\nArgs:\n    cbid (typing.Any): Description of `cbid`.\n    enabled (typing.Any): Description of `enabled`.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._impl.set_callback_enabled(cbid, enabled)

    def stop(self):
        """stop."""
        'stop.\n\nReturns:\n    typing.Any: Description of return value.'
        return self._impl.stop()

    def __contains__(self, key):
        return self._impl.exists(key)

    def __len__(self):
        try:
            return len(self._impl.keys())
        except Exception:
            return 0

    def __iter__(self):
        for k in self._impl.keys():
            yield k

class _DummyContext:
    """_DummyContext."""
    '_DummyContext class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = _DummyContext()'

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False