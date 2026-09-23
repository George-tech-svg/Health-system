# cache.py — simple in-memory cache with TTL for static/semi-static data
import time
import threading

_cache = {}
_lock = threading.Lock()


def get_or_set(key, fetch_fn, ttl_seconds=300):
    """
    Return cached value if fresh, else call fetch_fn and cache it.
    Default TTL: 5 minutes.
    """
    now = time.time()
    with _lock:
        entry = _cache.get(key)
        if entry:
            value, expires_at = entry
            if now < expires_at:
                return value

    # Cache miss — fetch outside the lock
    value = fetch_fn()
    with _lock:
        _cache[key] = (value, now + ttl_seconds)
    return value


def invalidate(key_prefix=None):
    """Clear entire cache or all keys starting with prefix."""
    with _lock:
        if key_prefix is None:
            _cache.clear()
        else:
            for k in list(_cache.keys()):
                if k.startswith(key_prefix):
                    _cache.pop(k, None)


def stats():
    with _lock:
        return {"entries": len(_cache), "keys": list(_cache.keys())}