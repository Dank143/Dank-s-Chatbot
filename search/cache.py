import asyncio
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


# --- Shared config cache -----------------------------------------------
# `load_config()` is called from hot request paths (e.g. every LLM rewrite
# in llm_processing.py). If the underlying loader does file I/O, calling it
# synchronously on every request blocks the event loop for every concurrent
# request, not just the caller. This wrapper amortizes that cost: it caches
# the loaded config for a short TTL (fresh enough that hot-reloaded values in
# models.yaml still land within a few seconds) and, when the cache does need
# to refresh, runs the loader off-thread so even that refresh never blocks
# the event loop.
_CONFIG_TTL = 5.0
_config_cache: dict = {"value": None, "ts": 0.0}
_config_lock = asyncio.Lock()


async def get_cached_config(loader, ttl: float = _CONFIG_TTL) -> dict:
    """TTL-cached, off-thread wrapper around a synchronous config loader.

    Safe to call from any hot async path. Concurrent callers during a
    refresh share a single loader invocation via the lock rather than each
    triggering their own reload.
    """
    now = time.monotonic()
    if _config_cache["value"] is not None and (now - _config_cache["ts"]) < ttl:
        return _config_cache["value"]

    async with _config_lock:
        # Re-check after acquiring the lock — another task may have already
        # refreshed it while we were waiting.
        now = time.monotonic()
        if _config_cache["value"] is not None and (now - _config_cache["ts"]) < ttl:
            return _config_cache["value"]
        value = await asyncio.to_thread(loader)
        _config_cache["value"] = value
        _config_cache["ts"] = now
        return value