import asyncio
import logging
import sys
from collections import OrderedDict
from urllib.parse import urlparse

import httpx

try:
    import trafilatura as _trafilatura
except ImportError:
    _trafilatura = None

_log = logging.getLogger(__name__)

async def warmup_jina():
    try:
        await _jina_client.get("https://r.jina.ai/https://example.com")
        _log.debug("Jina warmup ok")
    except Exception:
        _log.debug("Jina warmup failed", exc_info=True)

_JINA_BASE = "https://r.jina.ai/"
_MAX_CHARS = 20000
_MIN_CHARS = 500
_MIN_SNIPPET = 80
_JINA_TIMEOUT = 5.0

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_limits = httpx.Limits(max_keepalive_connections=50, max_connections=200)
_jina_client = httpx.AsyncClient(timeout=_JINA_TIMEOUT, follow_redirects=True, limits=_limits)
_fetch_client = httpx.AsyncClient(timeout=6.0, follow_redirects=True, headers=_BROWSER_HEADERS, limits=_limits)

_MW_HEADERS = {"User-Agent": "NIMChatbot/1.0 (web-search; contact vibecodersunity@gmail.com)"}
_mw_client = httpx.AsyncClient(timeout=6.0, follow_redirects=True, headers=_MW_HEADERS, limits=_limits)

_SKIP_DOMAINS = {
    "twitter.com", "x.com",
    "instagram.com", "tiktok.com", "facebook.com",
}


class _BoundedLRU(OrderedDict):
    """LRU cache capped at `maxsize` entries."""

    def __init__(self, maxsize: int = 2000):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default


_MW_PAGE_PREFIXES = ("/wiki/", "/w/")
_MW_API_CANDIDATES = ("/w/api.php", "/api.php")
_mw_endpoint_cache: "_BoundedLRU" = _BoundedLRU(maxsize=2000)


def skip(url: str, allowed: "frozenset[str]" = frozenset()) -> bool:
    try:
        host = urlparse(url).hostname or ""
        if any(host == d or host.endswith("." + d) for d in allowed):
            return False
        return any(host == d or host.endswith("." + d) for d in _SKIP_DOMAINS)
    except Exception:
        return False


def truncate(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    cut = text[:_MAX_CHARS].rsplit(". ", 1)
    return (cut[0] + ".") if len(cut) > 1 else text[:_MAX_CHARS]


async def _extract(html: str) -> str:
    """Run trafilatura off-thread; drop content under _MIN_CHARS."""
    if not html or _trafilatura is None:
        return ""
    text = await asyncio.to_thread(
        _trafilatura.extract, html,
        include_comments=False, include_tables=True, no_fallback=False,
        favor_recall=True,
    ) or ""
    return truncate(text) if len(text) >= _MIN_CHARS else ""


async def _jina_fetch(url: str) -> str:
    try:
        res = await _jina_client.get(f"{_JINA_BASE}{url}", headers={"Accept": "text/plain"})
        res.raise_for_status()
        text = res.text
        if len(text) < _MIN_CHARS or "Just a moment" in text or "Ray ID:" in text:
            return ""
        return truncate(text)
    except Exception:
        _log.debug("Jina fetch failed for %r", url, exc_info=True)
        return ""


async def _trafilatura_fetch(url: str) -> str:
    if _trafilatura is None:
        return ""
    try:
        resp = await _fetch_client.get(url)
        resp.raise_for_status()
        return await _extract(resp.text)
    except Exception:
        _log.debug("Trafilatura fetch failed for %r", url, exc_info=True)
        return ""


async def _detect_mediawiki(host: str) -> "str | None":
    """Probe api.php candidates; cache the working endpoint."""
    if host in _mw_endpoint_cache:
        return _mw_endpoint_cache[host]

    async def _probe(api_url: str) -> "str | None":
        try:
            r = await _mw_client.get(
                api_url, params={"action": "query", "meta": "siteinfo", "format": "json"}
            )
            if (
                r.status_code == 200
                and "application/json" in r.headers.get("content-type", "")
                and "query" in r.json()
            ):
                return api_url
        except Exception:
            pass
        return None

    results = await asyncio.gather(
        *[_probe(f"https://{host}{p}") for p in _MW_API_CANDIDATES]
    )
    endpoint = next((u for u in results if u), None)
    _mw_endpoint_cache[host] = endpoint
    return endpoint


def _mediawiki_title(path: str) -> "str | None":
    for prefix in _MW_PAGE_PREFIXES:
        if path.startswith(prefix):
            return path[len(prefix):] or None
    return None


async def _mediawiki_api(api_url: str, title: str, client: httpx.AsyncClient) -> str:
    resp = await client.get(api_url, params={
        "action": "query",
        "titles": title,
        "redirects": 1,
        "prop": "extracts",
        "explaintext": 1,
        "exsectionformat": "plain",
        "format": "json",
    })
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    return next(iter(pages.values()), {}).get("extract", "")


# Subpages where extracts API returns empty (content is in wiki templates)
_TEMPLATE_HEAVY = {"audio", "quotes", "voicelines", "voice_lines", "trivia", "sounds"}


async def _mediawiki_fetch(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or ""
        if not host:
            return ""
        page_title = _mediawiki_title(parsed.path)
        if page_title is None:
            return ""
        segments = page_title.split("/")
        if any(seg.lower() in _TEMPLATE_HEAVY for seg in segments):
            return ""  # Let Jina/trafilatura handle template-heavy pages
        api_url = await _detect_mediawiki(host)
        if api_url is None:
            return ""
        text = await _mediawiki_api(api_url, page_title, _mw_client)
        while len(text) < 10 and len(segments) > 1:
            segments = segments[:-1]
            text = await _mediawiki_api(api_url, "/".join(segments), _mw_client)
        return truncate(text) if len(text) >= _MIN_CHARS else ""
    except Exception:
        _log.debug("MediaWiki fetch failed for %r", url, exc_info=True)
        return ""


async def _reddit_fetch(url: str) -> str:
    """Fetch reddit via JSON API instead of scraping."""
    try:
        parsed = urlparse(url)
        path = parsed.path
        if not path.endswith('.json'):
            if path.endswith('/'):
                path = path[:-1]
            path += '.json'
            
        json_url = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            json_url += f"?{parsed.query}"
            
        resp = await _fetch_client.get(json_url, headers=_BROWSER_HEADERS, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        
        if not isinstance(data, list) or len(data) < 2:
            return ""
            
        post_data = data[0]["data"]["children"][0]["data"]
        title = post_data.get("title", "")
        selftext = post_data.get("selftext", "")
        
        content = f"Title: {title}\nPost: {selftext}\n\nTop Comments:\n"
        
        comments = data[1]["data"]["children"]
        for c in comments[:5]:
            c_data = c.get("data", {})
            body = c_data.get("body", "")
            if body and body not in ("[deleted]", "[removed]"):
                content += f"- {body}\n"
                
        return truncate(content) if len(content) >= 50 else ""
    except Exception:
        _log.debug("Reddit JSON fetch failed for %r", url, exc_info=True)
        return ""


_FETCHERS = {
    "mediawiki": _mediawiki_fetch,
    "jina": _jina_fetch,
    "trafilatura": _trafilatura_fetch,
}
_host_fetcher: "_BoundedLRU" = _BoundedLRU(maxsize=2000)  # host -> last-successful fetcher


async def _race(url: str, labels: list[str]) -> tuple[str, str]:
    """Race fetchers; return (text, label) of first non-empty."""
    async def _labeled(label):
        return label, await _FETCHERS[label](url)

    futs = [asyncio.ensure_future(_labeled(l)) for l in labels]
    try:
        for coro in asyncio.as_completed(futs):
            label, text = await coro
            if text:
                return text, label
    except Exception:
        pass
    finally:
        for f in futs:
            if not f.done():
                f.cancel()
    return "", ""


async def fetch_content(url: str, snippet: str = "") -> tuple[str, str]:
    """Fetch page text via mediawiki/jina/trafilatura race, with snippet fallback."""
    host = urlparse(url).hostname or ""
    
    if host == "reddit.com" or host.endswith(".reddit.com"):
        text = await _reddit_fetch(url)
        if text:
            return text, "reddit"

    known = _host_fetcher.get(host)

    # Fast path: try host's proven fetcher first
    if known:
        try:
            text = await asyncio.wait_for(_FETCHERS[known](url), timeout=2.5)
            if text:
                return text, known
        except (Exception, asyncio.TimeoutError):
            pass

    # Race remaining fetchers
    skip_labels = {known} if known else set()
    rest = [l for l in _FETCHERS if l not in skip_labels]
    
    if rest:
        text, label = await _race(url, rest)
        if text:
            _host_fetcher[host] = label
            return text, label

    if len(snippet.strip()) >= _MIN_SNIPPET:
        return snippet[:1000], "snippet"
    return "", "failed"


async def shutdown_fetchers():
    """Close HTTPX clients on shutdown."""
    await _jina_client.aclose()
    await _fetch_client.aclose()
    await _mw_client.aclose()
