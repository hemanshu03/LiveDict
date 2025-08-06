import time
import threading
import pytest
import redis
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.core import LiveDict, SandboxTimeout

# Helper hooks
access_calls = []
expire_calls = []

def on_access_hook(key, value):
    access_calls.append((key, value))

def on_expire_hook(key):
    expire_calls.append(key)

# Dummy auth function
def allow_all(op, key):
    return True

def deny_set(op, key):
    return op != 'set'

@pytest.fixture
def clean_redis():
    r = redis.Redis.from_url("redis://127.0.0.1:6379/0")
    r.flushdb()
    yield r
    r.flushdb()

@pytest.mark.parametrize("use_redis,serializer", [
    (False, 'json'),
    (False, 'msgpack'),
    (True,  'json'),
    (True,  'msgpack'),
])
def test_set_get_delete(clean_redis, use_redis, serializer):
    # Skip msgpack tests if not installed
    if serializer == 'msgpack':
        try:
            import msgpack
        except ImportError:
            pytest.skip("msgpack not installed")

    # Setup LiveDict
    redis_client = clean_redis if use_redis else None
    ld = LiveDict(
        default_ttl=2,
        auth_func=allow_all,
        serializer=serializer,
        encryption_keys=None,
        redis_client=redis_client,
        enable_redis=use_redis
    )

    # Basic set/get
    ld.set('foo', {'bar': 123}, on_access=on_access_hook, on_expire=on_expire_hook)
    val = ld.get('foo')
    assert val == {'bar': 123}
    assert access_calls.pop() == ('foo', {'bar': 123})

    # Test delete
    ld.delete('foo')
    assert ld.get('foo') is None

    # Redis persistence check
    if use_redis:
        # Set directly in redis
        clean_redis.set('x', b'data')
        # Should get None because invalid encryption
        assert ld.get('x') is None

    ld.stop()

@pytest.mark.parametrize("serializer", ['json', 'msgpack'])
def test_ttl_and_expiry(serializer):
    if serializer == 'msgpack':
        try:
            import msgpack
        except ImportError:
            pytest.skip("msgpack not installed")

    # Fresh counters
    expire_calls.clear()

    ld = LiveDict(default_ttl=1, auth_func=allow_all, serializer=serializer)
    ld.set('temp', 'value', ttl=1, on_expire=on_expire_hook)
    # Wait for expiry
    time.sleep(1.5)
    # Trigger monitor manually
    assert 'temp' not in ld._store
    # Give time for hook
    time.sleep(0.1)
    assert expire_calls == ['temp']
    ld.stop()

def test_key_rotation_and_encryption():
    ld = LiveDict(default_ttl=10, auth_func=allow_all, serializer='json')
    # Set before rotation
    ld.set('a', 1)
    # Rotate key
    new_key = AESGCM.generate_key(256)
    ld.rotate_key(new_key)
    # Set after rotation
    ld.set('b', 2)
    # Both keys should decrypt correctly
    assert ld.get('a') == 1
    assert ld.get('b') == 2
    ld.stop()

def test_acl_restrictions():
    # Deny set
    ld = LiveDict(default_ttl=10, auth_func=deny_set)
    with pytest.raises(PermissionError):
        ld.set('nope', 123)
    # Allow get/delete by default
    ld = LiveDict(default_ttl=10, auth_func=deny_set)
    # Inject directly
    ld._store['x'] = ld._store.get('x')  # dummy
    # get and delete should not raise
    _ = ld.get('x')
    ld.delete('x')
    ld.stop()

def test_sandbox_timeout():
    def long_hook(key, val=None):
        time.sleep(2)
    ld = LiveDict(default_ttl=10, auth_func=allow_all)
    with pytest.raises(SandboxTimeout):
        ld.set('k', 'v', on_access=long_hook)
        _ = ld.get('k')
    ld.stop()
