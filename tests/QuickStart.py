from livedict import LiveDict

store = LiveDict(default_ttl=5)
store.set("foo", {"bar": 123})
print(store.get("foo"))  # {'bar': 123}
