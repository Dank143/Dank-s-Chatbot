import logging
import os
import time

import httpx

from .fetcher import content_is_usable, truncate

_log = logging.getLogger(__name__)

_limits = httpx.Limits(max_keepalive_connections=20, max_connections=40)
_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=3.0),
    follow_redirects=True,
    limits=_limits,
)


class _CircuitBreaker:
    """Temporarily skip a provider after repeated transport/server failures."""

    def __init__(self, name: str, threshold: int = 3, cooldown: float = 20.0):
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures = 0
        self._open_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._open_until = time.monotonic() + self.cooldown
            _log.warning(
                "%s circuit breaker opened for %.0fs after %d failures",
                self.name,
                self.cooldown,
                self._failures,
            )


_exa_breaker = _CircuitBreaker("Exa")
_tavily_breaker = _CircuitBreaker("Tavily")
_firecrawl_breaker = _CircuitBreaker("Firecrawl")


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _score(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _result(
    *,
    url: str,
    title: str = "",
    snippet: str = "",
    content: str = "",
    provider: str,
    score: float = 0.0,
) -> dict:
    """Normalize provider responses into the pipeline's shared result shape."""
    return {
        "url": _text(url),
        "title": _text(title),
        "snippet": _text(snippet),
        "content": truncate(_text(content)),
        "content_provider": provider,
        "score": _score(score),
    }


def _log_provider_error(provider: str, response: httpx.Response) -> None:
    body = response.text.replace("\n", " ")[:500]
    _log.warning("%s returned HTTP %d: %s", provider, response.status_code, body)


async def _exa_search(query: str, max_results: int = 5) -> list[dict]:
    """Search Exa and request one full-text content type for each result."""
    api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not api_key or _exa_breaker.is_open():
        return []

    try:
        response = await _client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key},
            json={
                "query": query,
                "type": "fast",
                "numResults": min(max(1, max_results), 5),
                "contents": {
                    "text": {"maxCharacters": 8000},
                    "livecrawlTimeout": 2000,
                },
            },
        )
        if response.status_code != 200:
            _log_provider_error("Exa", response)
            if response.status_code >= 500:
                _exa_breaker.record_failure()
            return []

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Exa response is not an object")
        results = [
            _result(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=(item.get("text") or "")[:1000],
                content=item.get("text") or "",
                provider="exa",
                score=item.get("score", 0.0),
            )
            for item in data.get("results", [])
            if isinstance(item, dict) and item.get("url")
        ]
        _exa_breaker.record_success()
        _log.info(
            "Exa returned %d results (%d with usable content)",
            len(results),
            sum(content_is_usable(item["content"]) for item in results),
        )
        return results
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        _log.warning("Exa request failed: %s", exc)
        _exa_breaker.record_failure()
        return []


async def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Search Tavily and request cleaned Markdown in the same API call."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key or _tavily_breaker.is_open():
        return []

    try:
        response = await _client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": min(max(1, max_results), 5),
                "include_answer": False,
                "include_raw_content": "markdown",
                "include_images": False,
                "auto_parameters": False,
                "include_usage": True,
            },
        )
        if response.status_code != 200:
            _log_provider_error("Tavily", response)
            if response.status_code >= 500:
                _tavily_breaker.record_failure()
            return []

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Tavily response is not an object")
        results = [
            _result(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", ""),
                content=item.get("raw_content") or "",
                provider="tavily",
                score=item.get("score", 0.0),
            )
            for item in data.get("results", [])
            if isinstance(item, dict) and item.get("url")
        ]
        _tavily_breaker.record_success()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        _log.info(
            "Tavily returned %d results (%d with usable content) in %ss; credits=%s",
            len(results),
            sum(content_is_usable(item["content"]) for item in results),
            data.get("response_time", "?"),
            usage.get("credits", "?"),
        )
        return results
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        _log.warning("Tavily request failed: %s", exc)
        _tavily_breaker.record_failure()
        return []


def _firecrawl_items(data: dict) -> list[dict]:
    """Accept both the current v2 `data.web` and the legacy list response."""
    payload = data.get("data", [])
    if isinstance(payload, dict):
        payload = payload.get("web", [])
    return payload if isinstance(payload, list) else []


def _valid_firecrawl_item(item: dict) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    status = metadata.get("statusCode")
    try:
        status_ok = status is None or 200 <= int(status) < 400
    except (TypeError, ValueError):
        status_ok = False
    return (
        bool(item.get("url") or metadata.get("sourceURL") or metadata.get("url"))
        and not metadata.get("error")
        and status_ok
    )


async def _firecrawl_search(
    query: str, max_results: int = 5, timeout_ms: int = 6000,
) -> list[dict]:
    """Last-resort Firecrawl search with Markdown extraction in one request."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key or _firecrawl_breaker.is_open():
        return []

    timeout_ms = max(1000, min(timeout_ms, 7000))
    try:
        response = await _client.post(
            "https://api.firecrawl.dev/v2/search",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "limit": min(max(1, max_results), 5),
                "timeout": timeout_ms,
                "ignoreInvalidURLs": True,
                "scrapeOptions": {
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                    "timeout": max(1000, timeout_ms - 500),
                },
            },
        )
        if response.status_code != 200:
            _log_provider_error("Firecrawl Search", response)
            if response.status_code >= 500:
                _firecrawl_breaker.record_failure()
            return []

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Firecrawl Search response is not an object")
        if data.get("success") is False:
            _log.warning("Firecrawl Search reported an unsuccessful request")
            return []
        results = []
        for item in _firecrawl_items(data):
            if not isinstance(item, dict) or not _valid_firecrawl_item(item):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            results.append(_result(
                url=item.get("url") or metadata.get("sourceURL") or metadata.get("url") or "",
                title=item.get("title") or metadata.get("title") or "",
                snippet=item.get("description") or metadata.get("description") or "",
                content=item.get("markdown") or "",
                provider="firecrawl",
            ))
        _firecrawl_breaker.record_success()
        _log.info(
            "Firecrawl Search returned %d results; credits=%s",
            len(results),
            data.get("creditsUsed", "?"),
        )
        return results
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        _log.warning("Firecrawl Search failed: %s", exc)
        _firecrawl_breaker.record_failure()
        return []


async def _firecrawl_scrape(url: str, timeout_ms: int = 5500) -> str:
    """Repair one known URL with Firecrawl's basic Markdown scraper."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key or _firecrawl_breaker.is_open():
        return ""

    timeout_ms = max(1000, min(timeout_ms, 6500))
    try:
        response = await _client.post(
            "https://api.firecrawl.dev/v2/scrape",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "timeout": timeout_ms,
            },
        )
        if response.status_code != 200:
            _log_provider_error("Firecrawl Scrape", response)
            if response.status_code >= 500:
                _firecrawl_breaker.record_failure()
            return ""

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Firecrawl Scrape response is not an object")
        page = data.get("data") if isinstance(data.get("data"), dict) else {}
        metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
        status = metadata.get("statusCode")
        if (
            data.get("success") is False
            or metadata.get("error")
            or (status is not None and not 200 <= int(status) < 400)
        ):
            return ""
        text = truncate((page.get("markdown") or "").strip())
        if text:
            _firecrawl_breaker.record_success()
        return text
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        _log.warning("Firecrawl Scrape failed for %s: %s", url, exc)
        _firecrawl_breaker.record_failure()
        return ""


async def shutdown_engines() -> None:
    await _client.aclose()
