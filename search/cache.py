import time

_CACHE_TTL = 300
# Short TTL for empty/timed-out results. A query that reliably fails
# (dead site, bad rewrite, downstream outage) would otherwise re-run the
# full pipeline on every single retry; a short negative TTL absorbs
# bursty repeats (e.g. a user re-sending, or several chats hitting the
# same failing query within seconds) while still recovering fast once
# the underlying issue clears, rather than staying stale for 5 minutes.
_NEGATIVE_CACHE_TTL = 30
_MAX_ENTRIES = 200
_cache: dict[tuple, tuple] = {}

def _cache_get(key: tuple) -> "tuple[str, dict] | None":
    entry = _cache.get(key)
    if entry is None:
        return None
    value, ts, ttl = entry
    if time.monotonic() - ts < ttl:
        return value
    del _cache[key]
    return None

def _cache_set(key: tuple, value: "tuple[str, dict]", ttl: "float | None" = None) -> None:
    """Store a result. Pass ttl=_NEGATIVE_CACHE_TTL for empty/failed results;
    defaults to the normal 5-minute TTL otherwise."""
    now = time.monotonic()
    effective_ttl = ttl if ttl is not None else _CACHE_TTL

    expired = [k for k, (v, ts, entry_ttl) in _cache.items() if now - ts >= entry_ttl]
    for k in expired:
        del _cache[k]

    if len(_cache) >= _MAX_ENTRIES:
        oldest = min(_cache.keys(), key=lambda k: _cache[k][1])
        del _cache[oldest]

    _cache[key] = (value, now, effective_ttl)
