"""storage_backend.py — LiveDict v2 module.

Module contains implementations for LiveDict core components."""
import threading
import time
import pickle
from typing import Any, Optional, Dict, List, Tuple

class BaseBackendMethods:
    """BaseBackendMethods.

        Storage backend implementing basic key/value operations used by LiveDict.
        Concrete backends may store data in memory, SQLite, or Redis.

        Methods should implement: get(key, default=None), set(key, value, ttl=None),
        delete(key), exists(key).
"""
    'BaseBackendMethods class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = BaseBackendMethods()'

    def __init__(self):
        self._lock = threading.RLock()

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
        with self._lock:
            return self._set_value(key, value, ttl)

    def get(self, key: str, default=None):
        """get.

        Retrieve a value for the specified key.

        Args:
            key (str): Key to retrieve.
            default (typing.Any): Value to return if key is not present.

        Returns:
            typing.Any: The stored value or `default` if key does not exist.
"""
        'get.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    default (typing.Any): Description of `default`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._lock:
            return self._get_value(key, default)

    def delete(self, key: str):
        """delete.

        Delete a key from the store.

        Args:
            key (str): Key to delete.

        Returns:
            bool: True if the key existed and was deleted, False otherwise.
"""
        'delete.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._lock:
            return self._delete_value(key)

    def items(self) -> List[Tuple[str, Any]]:
        """items."""
        'items.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._lock:
            return self._items()

    def keys(self) -> List[str]:
        """keys."""
        'keys.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._lock:
            return self._keys()

    def exists(self, key: str) -> bool:
        """exists.

        Check whether a key exists in the store.

        Args:
            key (str): Key to check.

        Returns:
            bool: True if key exists, False otherwise.
"""
        'exists.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._lock:
            return self._exists(key)

    def len(self) -> int:
        """len."""
        'len.\n\nReturns:\n    typing.Any: Description of return value.'
        with self._lock:
            return len(self._keys())

class MemoryBackend(BaseBackendMethods):
    """MemoryBackend.

        Storage backend implementing basic key/value operations used by LiveDict.
        Concrete backends may store data in memory, SQLite, or Redis.

        Methods should implement: get(key, default=None), set(key, value, ttl=None),
        delete(key), exists(key).
"""
    'MemoryBackend class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = MemoryBackend()'

    def __init__(self):
        super().__init__()
        self._store: Dict[str, Any] = {}
        self._ttls: Dict[str, float] = {}

    def _set_value(self, key: str, value: Any, ttl: Optional[float]=None):
        """_set_value."""
        '_set_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    value (typing.Any): Description of `value`.\n    ttl (typing.Any): Description of `ttl`.\n\nReturns:\n    typing.Any: Description of return value.'
        self._store[key] = value
        if ttl is not None:
            self._ttls[key] = time.time() + ttl
        else:
            self._ttls.pop(key, None)

    def _get_value(self, key: str, default=None):
        """_get_value."""
        '_get_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    default (typing.Any): Description of `default`.\n\nReturns:\n    typing.Any: Description of return value.'
        exp = self._ttls.get(key)
        if exp is not None and time.time() >= exp:
            self._store.pop(key, None)
            self._ttls.pop(key, None)
            return default
        return self._store.get(key, default)

    def _delete_value(self, key: str):
        """_delete_value."""
        '_delete_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        self._store.pop(key, None)
        self._ttls.pop(key, None)

    def _items(self) -> List[Tuple[str, Any]]:
        """_items."""
        '_items.\n\nReturns:\n    typing.Any: Description of return value.'
        now = time.time()
        result = []
        for k in list(self._store.keys()):
            exp = self._ttls.get(k)
            if exp is not None and now >= exp:
                self._store.pop(k, None)
                self._ttls.pop(k, None)
                continue
            result.append((k, self._store[k]))
        return result

    def _keys(self) -> List[str]:
        """_keys."""
        '_keys.\n\nReturns:\n    typing.Any: Description of return value.'
        now = time.time()
        keys = []
        for k in list(self._store.keys()):
            exp = self._ttls.get(k)
            if exp is not None and now >= exp:
                self._store.pop(k, None)
                self._ttls.pop(k, None)
                continue
            keys.append(k)
        return keys

    def _exists(self, key: str) -> bool:
        """_exists."""
        '_exists.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        exp = self._ttls.get(key)
        if exp is not None and time.time() >= exp:
            self._store.pop(key, None)
            self._ttls.pop(key, None)
            return False
        return key in self._store

class SQLiteBackend(BaseBackendMethods):
    """SQLiteBackend.

        Storage backend implementing basic key/value operations used by LiveDict.
        Concrete backends may store data in memory, SQLite, or Redis.

        Methods should implement: get(key, default=None), set(key, value, ttl=None),
        delete(key), exists(key).
"""
    'SQLiteBackend class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = SQLiteBackend()'

    def __init__(self, db_path: str=':memory:', client: Optional[object]=None):
        super().__init__()
        import sqlite3
        if client is not None:
            if not isinstance(client, sqlite3.Connection):
                raise TypeError('client must be a sqlite3.Connection for SQLiteBackend')
            self.conn = client
            self._own_conn = False
        else:
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self._own_conn = True
        self._ensure_table()

    def _ensure_table(self):
        """_ensure_table."""
        '_ensure_table.\n\nReturns:\n    typing.Any: Description of return value.'
        cur = self.conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value BLOB, expire REAL)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_kv_expire ON kv_store(expire)')
        self.conn.commit()

    def _set_value(self, key: str, value: Any, ttl: Optional[float]=None):
        """_set_value."""
        '_set_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    value (typing.Any): Description of `value`.\n    ttl (typing.Any): Description of `ttl`.\n\nReturns:\n    typing.Any: Description of return value.'
        exp = time.time() + ttl if ttl is not None else None
        raw = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        cur = self.conn.cursor()
        cur.execute('REPLACE INTO kv_store (key, value, expire) VALUES (?, ?, ?)', (key, raw, exp))
        self.conn.commit()

    def _get_value(self, key: str, default=None):
        """_get_value."""
        '_get_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    default (typing.Any): Description of `default`.\n\nReturns:\n    typing.Any: Description of return value.'
        cur = self.conn.cursor()
        cur.execute('SELECT value, expire FROM kv_store WHERE key=?', (key,))
        row = cur.fetchone()
        if not row:
            return default
        raw, exp = row
        if exp is not None and time.time() >= exp:
            cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
            self.conn.commit()
            return default
        try:
            return pickle.loads(raw)
        except Exception:
            cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
            self.conn.commit()
            return default

    def _delete_value(self, key: str):
        """_delete_value."""
        '_delete_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        cur = self.conn.cursor()
        cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
        self.conn.commit()

    def _items(self) -> List[Tuple[str, Any]]:
        """_items."""
        '_items.\n\nReturns:\n    typing.Any: Description of return value.'
        cur = self.conn.cursor()
        cur.execute('SELECT key, value, expire FROM kv_store')
        now = time.time()
        out = []
        for key, raw, exp in cur.fetchall():
            if exp is not None and now >= exp:
                cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
                continue
            try:
                out.append((key, pickle.loads(raw)))
            except Exception:
                cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
        self.conn.commit()
        return out

    def _keys(self) -> List[str]:
        """_keys."""
        '_keys.\n\nReturns:\n    typing.Any: Description of return value.'
        cur = self.conn.cursor()
        cur.execute('SELECT key, expire FROM kv_store')
        now = time.time()
        out = []
        for key, exp in cur.fetchall():
            if exp is not None and now >= exp:
                cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
                continue
            out.append(key)
        self.conn.commit()
        return out

    def _exists(self, key: str) -> bool:
        """_exists."""
        '_exists.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        cur = self.conn.cursor()
        cur.execute('SELECT expire FROM kv_store WHERE key=?', (key,))
        row = cur.fetchone()
        if not row:
            return False
        exp = row[0]
        if exp is not None and time.time() >= exp:
            cur.execute('DELETE FROM kv_store WHERE key=?', (key,))
            self.conn.commit()
            return False
        return True

    def __del__(self):
        try:
            if getattr(self, '_own_conn', False):
                self.conn.close()
        except Exception:
            pass

class RedisBackend(BaseBackendMethods):
    """RedisBackend.

        Storage backend implementing basic key/value operations used by LiveDict.
        Concrete backends may store data in memory, SQLite, or Redis.

        Methods should implement: get(key, default=None), set(key, value, ttl=None),
        delete(key), exists(key).
"""
    'RedisBackend class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = RedisBackend()'

    def __init__(self, url: Optional[str]=None, client: Optional[object]=None):
        super().__init__()
        try:
            import redis
            from redis import Redis
        except Exception as exc:
            raise RuntimeError('redis package is required for RedisBackend (pip install redis)') from exc
        if client is not None:
            if not isinstance(client, Redis):
                raise TypeError('client must be an instance of redis.Redis')
            self.client = client
        elif url is not None:
            self.client = Redis.from_url(url)
        else:
            raise ValueError("RedisBackend requires either 'url' or 'client'")

    def _set_value(self, key: str, value: Any, ttl: Optional[float]=None):
        """_set_value."""
        '_set_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    value (typing.Any): Description of `value`.\n    ttl (typing.Any): Description of `ttl`.\n\nReturns:\n    typing.Any: Description of return value.'
        raw = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        if ttl is not None:
            self.client.setex(name=key, time=int(ttl), value=raw)
        else:
            self.client.set(name=key, value=raw)

    def _get_value(self, key: str, default=None):
        """_get_value."""
        '_get_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n    default (typing.Any): Description of `default`.\n\nReturns:\n    typing.Any: Description of return value.'
        raw = self.client.get(key)
        if raw is None:
            return default
        try:
            return pickle.loads(raw)
        except Exception:
            try:
                self.client.delete(key)
            except Exception:
                pass
            return default

    def _delete_value(self, key: str):
        """_delete_value."""
        '_delete_value.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        try:
            self.client.delete(key)
        except Exception:
            pass

    def _items(self) -> List[Tuple[str, Any]]:
        """_items."""
        '_items.\n\nReturns:\n    typing.Any: Description of return value.'
        out = []
        try:
            keys = self.client.keys()
            for k in keys:
                try:
                    raw = self.client.get(k)
                    if raw is None:
                        continue
                    val = pickle.loads(raw)
                    key = k.decode() if isinstance(k, bytes) else k
                    out.append((key, val))
                except Exception:
                    try:
                        self.client.delete(k)
                    except Exception:
                        pass
        except Exception:
            return []
        return out

    def _keys(self) -> List[str]:
        """_keys."""
        '_keys.\n\nReturns:\n    typing.Any: Description of return value.'
        try:
            keys = self.client.keys()
            return [k.decode() if isinstance(k, bytes) else k for k in keys]
        except Exception:
            return []

    def _exists(self, key: str) -> bool:
        """_exists."""
        '_exists.\n\nArgs:\n    key (typing.Any): Description of `key`.\n\nReturns:\n    typing.Any: Description of return value.'
        try:
            return self.client.exists(key) > 0
        except Exception:
            return False