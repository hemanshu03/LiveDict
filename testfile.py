"""testfile.py — LiveDict v2 module.

Provides functionality for LiveDict package. Docstrings follow Google style.
"""
import asyncio
import time
import sqlite3
from livedict import LiveDict

def test_basic_sync():
    """test_basic_sync.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [1] Basic Sync CRUD (Memory Backend) ===')
    live = LiveDict(work_mode='sync', backend='memory')
    live.set('foo', 123)
    live.set('bar', 'hello')
    print('foo =', live.get('foo'))
    print('bar =', live.get('bar'))
    print("'foo' in live? ->", 'foo' in live)
    print('len(live) =', len(live))
    print('Keys:', list(live))
    print('Items:', live.items())
    live.delete('bar')
    print('After delete, bar =', live.get('bar'))

def test_ttl():
    """test_ttl.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [2] TTL / Expiry ===')
    live = LiveDict(work_mode='sync', backend='memory')
    live.set('temp', 'expire-me', ttl=2)
    print('Initially:', live.get('temp'))
    time.sleep(3)
    print('After 3s:', live.get('temp'))

def test_callbacks():
    """test_callbacks.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [3] Callbacks ===')
    live = LiveDict(work_mode='sync', backend='memory')

    def on_set(key, val):
        """on_set.

Args:
    key (typing.Any): Description of `key`.
    val (typing.Any): Description of `val`.

Returns:
    typing.Any: Description of return value."""
        print(f'[Callback] on_set sync: {key}={val}')

    async def on_expire(key, val):
        print(f'[Callback] on_expire async: {key} expired')
    cb1 = live.register_callback('set', on_set)
    cb2 = live.register_callback('expire', on_expire, is_async=True)
    live.set('foo', 'bar', ttl=1)
    time.sleep(2)
    live.set_callback_enabled(cb1, False)
    live.set('foo', 'baz')
    live.unregister_callback(cb2)
    live.set('temp', 'xxx', ttl=1)

def test_sandbox():
    """test_sandbox.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [4] Sandbox Safety ===')
    live = LiveDict(work_mode='sync', backend='memory')

    def bad_callback(key, val):
        """bad_callback.

Args:
    key (typing.Any): Description of `key`.
    val (typing.Any): Description of `val`.

Returns:
    typing.Any: Description of return value."""
        raise RuntimeError('Oops in callback')

    def slow_callback(key, val):
        """slow_callback.

Args:
    key (typing.Any): Description of `key`.
    val (typing.Any): Description of `val`.

Returns:
    typing.Any: Description of return value."""
        time.sleep(3)
    live.register_callback('set', bad_callback)
    live.register_callback('set', slow_callback, timeout=1.0)
    live.set('x', 99)
    time.sleep(2)

def test_locking():
    """test_locking.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [5] Per-Key Locking ===')
    live = LiveDict(work_mode='sync', backend='memory')
    live.set('counter', 1)
    if live.lock('counter', timeout=1):
        try:
            val = live.get('counter')
            live.set('counter', val + 1)
            print('Locked update done')
        finally:
            live.unlock('counter')
    print('Final value:', live.get('counter'))

async def test_async_memory():
    start = time.time()
    print(f"Start at {start}")
    """
    Test LiveDict in async mode with memory backend.
    """
    print('\n=== [6] Async Usage (Memory Backend) ===')
    live = LiveDict(work_mode='async', backend='memory')
    await live.set('a', 10, ttl=10)
    print('a =', await live.get('a'))

    async def async_cb(key, val):
        print(f'[Callback] async expire: {key}')

    async def async_cb2(key, val):
        print(f'[Callback2] async expire: {key}')

    async def main_callback(key, val):
        """
        Composite async callback for LiveDict expire events.

        Note:
            LiveDict only allows a single registered callback per event/key.
            Registering a new callback replaces the previous one.

        Usage:
            To invoke multiple async tasks on the same event, you can wrap
            them inside one "main" callback, as shown here. This way, 
            multiple coroutines (e.g. async_cb, async_cb2, etc.) can be 
            executed together when the event is triggered.

        Example:
            This main_callback launches two async expiration handlers and 
            waits for both to complete using asyncio.gather.
        """
        print(f"Call: {time.time() - start}")
        tasks = [async_cb(key, val), async_cb2(key, val)]
        await asyncio.gather(*tasks)
    live.register_callback('expire', main_callback, is_async=True, key='a')
    await live.set('b', 'bye', ttl=1)
    await asyncio.sleep(20)

def test_sqlite_sync():
    """test_sqlite_sync.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [7] SQLite Backend (Sync) ===')
    sqlite_client = sqlite3.connect('test.db', check_same_thread=False)
    live = LiveDict(work_mode='sync', backend='sqlite', client=sqlite_client)
    live.set('sqlkey', 'sqlite_value')
    print('sqlkey =', live.get('sqlkey'))

async def test_sqlite_async():
    """
    Test async mode with SQLite backend.
    """
    print('\n=== [7] SQLite Backend (Async) ===')
    sqlite_client = sqlite3.connect('test_async.db', check_same_thread=False)
    live = LiveDict(work_mode='async', backend='sqlite', client=sqlite_client)
    await live.set('sqlkey', 'sqlite_value_async')
    print('sqlkey =', await live.get('sqlkey'))

def test_redis_sync():
    """test_redis_sync.

Returns:
    typing.Any: Description of return value."""
    print('\n=== [8] Redis Backend (Sync) ===')
    try:
        from redis import Redis
        redis_client = Redis.from_url('redis://127.0.0.1:6379')
        live = LiveDict(work_mode='sync', backend='redis', client=redis_client)
        live.set('redkey', 'redis_value')
        print('redkey =', live.get('redkey'))
    except Exception as e:
        print('Redis not available:', e)

async def test_redis_async():
    """
    Test async mode with Redis backend.
    We still use sync redis client (operations run in executor).
    """
    print('\n=== [8] Redis Backend (Async) ===')
    try:
        from redis import Redis
        redis_client = Redis.from_url('redis://127.0.0.1:6379')
        live = LiveDict(work_mode='async', backend='redis', client=redis_client)
        await live.set('redkey', 'redis_value_async')
        print('redkey =', await live.get('redkey'))
    except Exception as e:
        print('Redis not available:', e)
if __name__ == '__main__':
    #test_basic_sync()
    #test_ttl()
    #test_callbacks()
    #test_sandbox()
    #test_locking()
    asyncio.run(test_async_memory())
    #test_sqlite_sync()
    #asyncio.run(test_sqlite_async())
    #test_redis_sync()
    #asyncio.run(test_redis_async())