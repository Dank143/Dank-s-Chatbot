import asyncio
import concurrent.futures
import logging
import os
import time
import httpx
from ddgs import DDGS
from .fetcher import skip

_log = logging.getLogger(__name__)

_DDG_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=32)
_FANDOM_ALLOW = frozenset({"fandom.com"})

_limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
_searxng_client = httpx.AsyncClient(timeout=7.5, limits=_limits)
_tavily_client = httpx.AsyncClient(timeout=10.0, limits=_limits)


class _CircuitBreaker:
    """Trip after N consecutive failures, then short-circuit calls for a
    cooldown window instead of paying the engine's full timeout on every
    request during an outage. Shared across all three engines so the same
    protection SearXNG had isn't a special case — DDG or Tavily going down
    used to still cost their full per-call timeout on every single search."""

    def __init__(self, name: str, threshold: int, cooldown: float):
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures = 0
        self._open_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._open_until = time.monotonic() + self.cooldown
            _log.warning(
                "%s circuit breaker tripped after %d consecutive failures; "
                "skipping for %.0fs", self.name, self._failures, self.cooldown
            )

_searxng_breaker = _CircuitBreaker("SearXNG", threshold=3, cooldown=30.0)
_ddg_breaker = _CircuitBreaker("DuckDuckGo", threshold=3, cooldown=20.0)
_tavily_breaker = _CircuitBreaker("Tavily", threshold=3, cooldown=20.0)

async def _searxng_search(query: str, max_results: int = 10) -> list[dict]:
    """Primary search via self-hosted SearXNG."""
    if _searxng_breaker.is_open():
        return []
    try:
        # Strict timeout so a cold SearXNG container doesn't hang the UI for 30s.
        resp = await asyncio.wait_for(
            _searxng_client.get(
                "http://localhost:8888/search",
                params={"q": query, "format": "json", "engines": "google,bing,duckduckgo,wikipedia"}
            ),
            timeout=5.0
        )
        if resp.status_code == 200:
            _searxng_breaker.record_success()
            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append({
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                    "title": r.get("title", "")
                })
            return results[:max_results]
        else:
            _searxng_breaker.record_failure()
    except Exception as e:
        _log.warning("SearXNG failed: %s", e)
        _searxng_breaker.record_failure()
    return []

async def _ddg_search(
    query: str, site: str | None = None, max_results: int = 10,
    allowed: "frozenset[str]" = frozenset(), max_attempts: int = 2,
) -> list[dict]:
    """Secondary search using DuckDuckGo library with multi-backend.

    max_attempts trimmed from 3->2 and backoff shortened from 0.5s/1.0s to
    0.3s/0.6s: the caller (pipeline._staggered_search_cascade) already wraps
    this whole call in a hard per-phase timeout, so extra local retries just
    eat into that shared budget rather than meaningfully improving hit rate.
    """
    if _ddg_breaker.is_open():
        return []
    search_query = f"site:{site} {query}" if site else query
    last_exc = None
    for attempt in range(max_attempts):
        try:
            # Instantiate DDGS per request to guarantee a fresh VQD token and avoid cross-thread async loop closures
            results = await asyncio.get_running_loop().run_in_executor(
                _DDG_EXECUTOR,
                lambda: list(DDGS(timeout=5.0).text(search_query, max_results=max_results, backend="duckduckgo,google,bing,brave,startpage"))
            )
            mapped = [
                {"url": r["href"], "snippet": r.get("body", ""), "title": r.get("title", "")}
                for r in (results or [])
                if r.get("href") and not skip(r["href"], allowed)
            ]
            if mapped:
                _ddg_breaker.record_success()
                return mapped
        except Exception as e:
            last_exc = e
        # Don't sleep after the final attempt — nothing left to wait for.
        if attempt < max_attempts - 1:
            await asyncio.sleep(0.3 * (attempt + 1))
    # Only count this against the breaker if every attempt actually raised —
    # a clean response with zero matches is a legitimate "no results", not an
    # engine failure, and shouldn't be able to trip the circuit.
    if last_exc is not None:
        _ddg_breaker.record_failure()
    else:
        _ddg_breaker.record_success()
    _log.warning("DDGS multi-backend failed for %r: %s", search_query, last_exc)
    return []

async def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Tertiary search using Tavily API (basic)."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return []
    if _tavily_breaker.is_open():
        return []
    try:
        resp = await _tavily_client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False
            }
        )
        if resp.status_code == 200:
            _tavily_breaker.record_success()
            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append({
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                    "title": r.get("title", "")
                })
            return results
        else:
            _log.warning("Tavily API returned %d: %s", resp.status_code, resp.text)
            _tavily_breaker.record_failure()
    except Exception as e:
        _log.warning("Tavily API failed: %s", e)
        _tavily_breaker.record_failure()
    return []

async def shutdown_engines() -> None:
    _DDG_EXECUTOR.shutdown(wait=False)
    await _searxng_client.aclose()
    await _tavily_client.aclose()
