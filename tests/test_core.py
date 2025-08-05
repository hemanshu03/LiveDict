import time
import pytest
from livedict import LiveDict, SandboxTimeout

def access_hook(key, value):
    print(f"[Access Hook] Accessed key={key}, value={value}")

def expire_hook(key):
    print(f"[Expire Hook] Key expired: {key}")

def long_running_hook(key, value):
    time.sleep(3)

def test_set_get():
    store = LiveDict(default_ttl=2)
    store.set("hello", {"world": True})
    assert store.get("hello") == {"world": True}
    store.stop()

def test_hooks_and_timeout():
    store = LiveDict(default_ttl=1)
    store.set("slow", 42, on_access=long_running_hook)
    with pytest.raises(SandboxTimeout):
        store.get("slow")
    store.stop()
