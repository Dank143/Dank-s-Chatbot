import asyncio
import time

_CACHE_TTL = 300
_NEGATIVE_CACHE_TTL = 30  # Short TTL for failed/empty results
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
    """Store a result. Use ttl=_NEGATIVE_CACHE_TTL for failed results."""
    now = time.monotonic()
    effective_ttl = ttl if ttl is not None else _CACHE_TTL

    expired = [k for k, (v, ts, entry_ttl) in _cache.items() if now - ts >= entry_ttl]
    for k in expired:
        del _cache[k]

    if len(_cache) >= _MAX_ENTRIES:
        oldest = min(_cache.keys(), key=lambda k: _cache[k][1])
        del _cache[oldest]

    _cache[key] = (value, now, effective_ttl)


# --- Shared config cache ---
_CONFIG_TTL = 5.0
_config_cache: dict = {"value": None, "ts": 0.0}
_config_lock = asyncio.Lock()


async def get_cached_config(loader, ttl: float = _CONFIG_TTL) -> dict:
    """TTL-cached, off-thread config loader. Concurrent callers share one reload."""
    now = time.monotonic()
    if _config_cache["value"] is not None and (now - _config_cache["ts"]) < ttl:
        return _config_cache["value"]

    async with _config_lock:
        now = time.monotonic()
        if _config_cache["value"] is not None and (now - _config_cache["ts"]) < ttl:
            return _config_cache["value"]
        value = await asyncio.to_thread(loader)
        _config_cache["value"] = value
        _config_cache["ts"] = now
        return value