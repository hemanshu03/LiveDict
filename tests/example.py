# test1.py

from livedict import LiveDict, SandboxTimeout
import time

def access_hook(key, value):
    print(f"[Access Hook] Accessed key={key}, value={value}")

def expire_hook(key):
    print(f"[Expire Hook] Key expired: {key}")

# Move this out of run_tests
def long_running_hook(key, value):
    time.sleep(3)  # exceeds timeout
    print("This should never print")

def run_tests():
    print("== LiveDict In-Memory Test ==")
    store = LiveDict(enable_redis_support=False, default_ttl=2)

    print("\n== TEST 1: Set & Get ==")
    store.set("hello", {"world": True})
    print("Retrieved:", store.get("hello"))

    print("\n== TEST 2: Set with Access Hook ==")
    store.set("test2", 12345, on_access=access_hook)
    val = store.get("test2")
    print("Hook worked. Value:", val)

    print("\n== TEST 3: Expiry & Expire Hook ==")
    store.set("short_lived", {"data": "vanish"}, ttl=1, on_expire=expire_hook)
    print("Sleeping 2 seconds for expiry...")
    time.sleep(2)
    print("Trying to get expired key:", store.get("short_lived"))

    print("\n== TEST 4: Delete ==")
    store.set("temp", "delete me")
    print("Before delete:", store.get("temp"))
    store.delete("temp")
    print("After delete:", store.get("temp"))

    print("\n== TEST 5: Sandbox Timeout ==")
    store.set("slow", 99, on_access=long_running_hook)
    store.get("slow")

    store.stop()
    print("\n== ALL TESTS DONE ==")

if __name__ == "__main__":
    run_tests()
