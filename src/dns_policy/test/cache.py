from cachetools import TLRUCache


def _myttu(_key, value, now):
    return now + value[1]


cache = TLRUCache(maxsize=1000, ttu=_myttu)

cache["a"] = (1, 30)
cache["b"] = (1, 30)


for key, value in cache.items():
    print(f"key: {key}, value:{value}")
