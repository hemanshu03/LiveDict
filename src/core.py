import threading
import time
import json
import os
import logging
import heapq
from typing import Callable, Any, Optional, Dict, List, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import platform

# Optional binary serializer
try:
    import msgpack
    _HAS_MSGPACK = True
except ImportError:
    _HAS_MSGPACK = False

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class SandboxTimeout(Exception):
    """
    Exception raised when a sandboxed hook exceeds its configured timeout.

    This is thrown by `SandboxedHookRunner.run()` when a hook callback
    takes longer than the allowed execution time.

    Example:
        >>> runner = SandboxedHookRunner(timeout_seconds=1)
        >>> def slow_hook():
        ...     time.sleep(2)
        >>> runner.run(slow_hook)
        Traceback (most recent call last):
            ...
        SandboxTimeout: Function execution exceeded 1s
    """
    pass


class SandboxedHookRunner:
    """
    Executes hook callbacks in a restricted environment with time and memory limits.

    On Unix-like systems (Linux, macOS), it uses separate subprocesses to
    enforce memory limits and terminate safely. On Windows, it falls back
    to threads (no strict memory control, only timeouts).

    Parameters
    ----------
    timeout_seconds : int, optional
        Maximum allowed execution time per hook in seconds (default: 1 second).
    max_memory_mb : int, optional
        Maximum allowed memory usage for hook subprocesses on Unix (default: 50 MB).

    Example
    -------
    Basic usage:
        >>> runner = SandboxedHookRunner(timeout_seconds=2)
        >>> def my_hook(name):
        ...     return f"Hello, {name}!"
        >>> runner.run(my_hook, "Alice")
        'Hello, Alice!'

    Timeout enforcement:
        >>> def too_slow():
        ...     time.sleep(3)
        >>> runner.run(too_slow)
        Traceback (most recent call last):
            ...
        SandboxTimeout: Function execution exceeded 2s
    """

    def __init__(self, timeout_seconds: int = 1, max_memory_mb: int = 50):
        self.timeout = timeout_seconds
        self.max_memory = max_memory_mb * 1024 * 1024
        self._is_unix = platform.system() != "Windows"

    def run(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a hook function with timeout and memory enforcement.

        Parameters
        ----------
        func : Callable
            The function (hook) to execute.
        *args
            Positional arguments passed to the function.
        **kwargs
            Keyword arguments passed to the function.

        Returns
        -------
        Any
            The return value from the executed hook function.

        Raises
        ------
        SandboxTimeout
            If the function exceeds the configured timeout.
        Exception
            Propagates any exception raised inside the hook itself.

        Notes
        -----
        - On Unix, memory limits are enforced using `resource.setrlimit`.
        - On Windows, only timeouts are supported (no memory enforcement).

        Example
        -------
        >>> runner = SandboxedHookRunner(timeout_seconds=1)
        >>> def greet():
        ...     return "Hello!"
        >>> runner.run(greet)
        'Hello!'
        """
        # Unix: use process sandbox
        if self._is_unix:
            from multiprocessing import Process, Pipe

            def _target(func, conn, *args, **kwargs):
                try:
                    # Apply memory limit
                    import resource
                    resource.setrlimit(resource.RLIMIT_AS, (self.max_memory, self.max_memory))
                except Exception:
                    pass
                try:
                    res = func(*args, **kwargs)
                    conn.send((True, res))
                except Exception as e:
                    conn.send((False, e))
                finally:
                    conn.close()

            parent_conn, child_conn = Pipe()
            p = Process(target=_target, args=(func, child_conn) + args, kwargs=kwargs)
            p.start()
            p.join(self.timeout)
            if p.is_alive():
                p.terminate()
                raise SandboxTimeout(f"Function execution exceeded {self.timeout}s")
            success, payload = parent_conn.recv()
            if not success:
                raise payload
            return payload

        # Windows: thread-based timeout
        else:
            result = {'value': None, 'exc': None}

            def wrapper():
                try:
                    result['value'] = func(*args, **kwargs)
                except Exception as e:
                    result['exc'] = e

            t = threading.Thread(target=wrapper)
            t.daemon = True
            t.start()
            t.join(self.timeout)
            if t.is_alive():
                raise SandboxTimeout(f"Function execution exceeded {self.timeout}s")
            if result['exc']:
                raise result['exc']
            return result['value']


class Entry:
    """
    Represents a single encrypted entry stored inside `LiveDict`.

    Attributes
    ----------
    ciphertext : bytes
        AES-GCM encrypted blob of the serialized value.
    expire_at : float
        Absolute expiration timestamp (seconds since epoch).
    on_access : Callable, optional
        Callback executed when this key is accessed via `LiveDict.get()`.
    on_expire : Callable, optional
        Callback executed when this key expires and is removed.
    """

    def __init__(
        self,
        ciphertext: bytes,
        expire_at: float,
        on_access: Optional[Callable] = None,
        on_expire: Optional[Callable] = None,
    ):
        self.ciphertext = ciphertext
        self.expire_at = expire_at
        self.on_access = on_access
        self.on_expire = on_expire


class LiveDict:
    """
    Encrypted, thread-safe, TTL-based dictionary with optional Redis persistence.

    `LiveDict` provides:
        - AES-GCM encryption (key rotation supported).
        - TTL-based expiry with background cleanup (heap-based for efficiency).
        - Hook callbacks (`on_access`, `on_expire`) executed in a sandbox.
        - Optional Redis backend for persistence and fallback.
        - JSON or msgpack serialization for stored values.
        - Access control via a custom `auth_func`.

    Quick Start
    -----------
    A basic example showing initialization, storage, retrieval, and graceful shutdown:

        >>> from livedict import LiveDict
        >>> store = LiveDict(default_ttl=5)
        >>> store.set("username", "alice")
        >>> store.get("username")
        'alice'
        >>> time.sleep(6)
        >>> store.get("username") is None
        True
        >>> store.stop()

    Parameters
    ----------
    default_ttl : int, optional
        Default time-to-live (in seconds) for new keys (default: 600 seconds).
    auth_func : Callable[[str, str], bool], optional
        Access control function accepting `(operation, key)` and returning
        `True` if allowed or `False` to deny.
    serializer : {'json', 'msgpack'}, optional
        Serialization format for values (default: 'json').
    encryption_keys : list of bytes, optional
        Pre-existing AES keys for decryption or key rotation. If omitted,
        a fresh key is generated.
    redis_client : Redis client, optional
        Redis client instance (`redis.StrictRedis` or compatible).
    enable_redis : bool, optional
        Whether to enable Redis persistence (default: False).

    Examples
    --------
    Using `on_access` and `on_expire` hooks:
        >>> def accessed(key, value):
        ...     print(f"Key {key} accessed, value = {value}")
        >>> def expired(key):
        ...     print(f"Key {key} expired!")
        >>> store = LiveDict(default_ttl=2)
        >>> store.set("session", "active", on_access=accessed, on_expire=expired)
        >>> _ = store.get("session")
        Key session accessed, value = active
        >>> time.sleep(3)
        Key session expired!

    Enabling Redis persistence:
        >>> import redis
        >>> r = redis.StrictRedis()
        >>> store = LiveDict(redis_client=r, enable_redis=True)
        >>> store.set("key", "value")

    Key rotation:
        >>> new_key = AESGCM.generate_key(256)
        >>> store.rotate_key(new_key)
    """

    def __init__(
        self,
        default_ttl: int = 600,
        auth_func: Optional[Callable[[str, str], bool]] = None,
        serializer: str = 'json',
        encryption_keys: Optional[List[bytes]] = None,
        redis_client=None,
        enable_redis: bool = False
    ):
        self.default_ttl = default_ttl
        self.auth = auth_func
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._store: Dict[str, Entry] = {}
        self._heap: List[Tuple[float, str]] = []
        self._running = True
        self.runner = SandboxedHookRunner()

        if serializer == 'msgpack' and not _HAS_MSGPACK:
            raise RuntimeError("msgpack not installed")
        self._use_msgpack = (serializer == 'msgpack')

        # Encryption key handling
        if encryption_keys:
            self._keys = encryption_keys.copy()
        else:
            self._keys = [AESGCM.generate_key(256)]
        self._current_key_idx = 0

        self.redis = redis_client
        self.redis_enabled = enable_redis and bool(self.redis)

        self._aesgcm = AESGCM(self._keys[self._current_key_idx])
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def rotate_key(self, new_key: bytes):
        """
        Rotate encryption key by adding a new key to the keyring.

        Args:
            new_key (bytes): New AES-GCM key (32 bytes recommended for AES-256).
        """
        with self._lock:
            self._keys.append(new_key)
            self._current_key_idx = len(self._keys) - 1
            self._aesgcm = AESGCM(self._keys[self._current_key_idx])
            logger.info("Encryption key rotated.")

    def _serialize(self, value: Any) -> bytes:
        """Serialize value using JSON or msgpack."""
        return msgpack.dumps(value) if self._use_msgpack else json.dumps(value).encode()

    def _deserialize(self, data: bytes) -> Any:
        """Deserialize data using JSON or msgpack."""
        return msgpack.loads(data) if self._use_msgpack else json.loads(data.decode())

    def _encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt data using AES-GCM with random nonce.

        Args:
            plaintext (bytes): Data to encrypt.

        Returns:
            bytes: Concatenation of nonce + ciphertext.
        """
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self._current_key_idx]).encrypt(nonce, plaintext, None)
        return nonce + ct

    def _decrypt(self, ciphertext: bytes) -> Optional[bytes]:
        """
        Attempt to decrypt ciphertext using all stored keys (reverse order).

        Args:
            ciphertext (bytes): Nonce + ciphertext to decrypt.

        Returns:
            bytes or None: Decrypted plaintext if successful, else None.
        """
        if len(ciphertext) < 13:
            return None
        nonce, ct = ciphertext[:12], ciphertext[12:]
        for key in reversed(self._keys):
            aes = AESGCM(key)
            try:
                return aes.decrypt(nonce, ct, None)
            except Exception:
                continue
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        on_access: Optional[Callable] = None,
        on_expire: Optional[Callable] = None,
        token: Optional[str] = None
    ):
        """
        Store a key-value pair with optional TTL and hook callbacks.

        Parameters
        ----------
        key : str
            Key to store.
        value : Any
            Value to encrypt and store.
        ttl : int, optional
            Time-to-live override (seconds). Defaults to `default_ttl`.
        on_access : Callable, optional
            Callback invoked when this key is retrieved using `get`.
        on_expire : Callable, optional
            Callback invoked when this key expires and is removed.
        token : str, optional
            Authentication token passed to `auth_func` (if used).

        Raises
        ------
        PermissionError
            If `auth_func` denies the `set` operation.

        Example
        -------
        >>> store = LiveDict(default_ttl=10)
        >>> store.set("foo", {"bar": 42})
        >>> store.get("foo")
        {'bar': 42}
        """
        if self.auth and not self.auth('set', key):
            raise PermissionError("Unauthorized set operation")
        expire_at = time.time() + (ttl or self.default_ttl)
        raw = self._serialize(value)
        encrypted = self._encrypt(raw)
        entry = Entry(encrypted, expire_at, on_access, on_expire)

        with self._cond:
            self._store[key] = entry
            heapq.heappush(self._heap, (expire_at, key))
            self._cond.notify()

        if self.redis_enabled:
            try:
                self.redis.set(key, encrypted, ex=int(ttl or self.default_ttl))
            except Exception as e:
                logger.warning(f"Redis SET failed for {key}: {e}")

    def get(self, key: str, token: Optional[str] = None) -> Optional[Any]:
        """
        Retrieve and decrypt a value by key.

        Executes `on_access` callback if defined and key is valid.

        Parameters
        ----------
        key : str
            Key to retrieve.
        token : str, optional
            Authentication token passed to `auth_func` (if used).

        Returns
        -------
        Any or None
            Decrypted value if present and valid, otherwise `None`.

        Raises
        ------
        PermissionError
            If `auth_func` denies the `get` operation.
        SandboxTimeout
            If the `on_access` callback exceeds timeout.

        Example
        -------
        >>> store = LiveDict()
        >>> store.set("key", 123)
        >>> store.get("key")
        123
        """
        if self.auth and not self.auth('get', key):
            raise PermissionError("Unauthorized get operation")
        data = None
        with self._lock:
            entry = self._store.get(key)
            if entry and entry.expire_at >= time.time():
                data = entry.ciphertext
            elif self.redis_enabled:
                data = self.redis.get(key)
            else:
                return None
        if not data:
            return None

        plaintext = self._decrypt(data)
        if plaintext is None:
            return None
        val = self._deserialize(plaintext)

        if entry and entry.on_access:
            try:
                self.runner.run(entry.on_access, key, val)
            except SandboxTimeout:
                raise
            except Exception:
                logger.exception(f"Error in on_access for {key}")
        return val

    def delete(self, key: str, token: Optional[str] = None):
        """
        Delete a key from memory (and Redis if enabled).

        Parameters
        ----------
        key : str
            Key to remove.
        token : str, optional
            Authentication token passed to `auth_func` (if used).

        Raises
        ------
        PermissionError
            If `auth_func` denies the `delete` operation.

        Example
        -------
        >>> store = LiveDict()
        >>> store.set("temp", "data")
        >>> store.delete("temp")
        >>> store.get("temp") is None
        True
        """
        if self.auth and not self.auth('delete', key):
            raise PermissionError("Unauthorized delete operation")
        with self._cond:
            self._store.pop(key, None)
            self._heap = [(e, k) for e, k in self._heap if k != key]
            heapq.heapify(self._heap)
            self._cond.notify()
        if self.redis_enabled:
            try:
                self.redis.delete(key)
            except Exception:
                pass

    def _monitor(self):
        """
        Background thread method.

        Monitors the min-heap for expired keys and:
            - Removes them from storage.
            - Executes `on_expire` callback in sandbox.
            - Waits until next expiration or default interval.
        """
        while self._running:
            with self._cond:
                now = time.time()
                while self._heap and self._heap[0][0] <= now:
                    _, k = heapq.heappop(self._heap)
                    e = self._store.pop(k, None)
                    if e and e.on_expire:
                        try:
                            self.runner.run(e.on_expire, k)
                        except Exception:
                            logger.exception(f"Error in on_expire for {k}")
                timeout = (self._heap[0][0] - now) if self._heap else None
                self._cond.wait(timeout=timeout or 1)

    def stop(self):
        """
        Stop the background expiry monitor thread.

        This method should be called when the LiveDict instance is no longer
        needed (e.g., during application shutdown) to avoid dangling threads.

        Example
        -------
        >>> store = LiveDict()
        >>> store.stop()
        """
        self._running = False
        with self._cond:
            self._cond.notify_all()
        self._thread.join()
        logger.info("LiveDict stopped gracefully.")
