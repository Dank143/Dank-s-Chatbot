import asyncio
import logging
import time
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

# Tier 1: High-trust domains (official docs, encyclopedias, news) independent of traffic.
_TIER1_DOMAINS = frozenset({
    "wikipedia.org", "wikidata.org", "britannica.com", "fandom.com",
    "developer.mozilla.org", "docs.python.org", "docs.microsoft.com",
    "learn.microsoft.com", "cloud.google.com", "docs.aws.amazon.com",
    "react.dev", "nodejs.org", "pypi.org", "github.com", "stackoverflow.com",
    "reuters.com", "apnews.com", "bbc.com", "npr.org",
})
_TIER1_SUFFIXES = (".gov", ".edu")
_TIER1_MULTIPLIER = 1.3

# Small manual list for known repeat offenders (e.g., zathong.com).
_DENYLIST = frozenset({
    "zathong.com",
})

# TLDs disproportionately favored by low-effort SEO / content-farm operators.
_SUSPICIOUS_TLDS = (".xyz", ".top", ".click", ".buzz", ".cfd", ".cyou", ".sbs", ".rest")
_SUSPICIOUS_TLD_MULTIPLIER = 0.85

# Flag URLs where the slug echoes the query verbatim (common in content farms).
_SLUG_STUFFING_THRESHOLD = 0.7
_SLUG_STUFFING_MULTIPLIER = 0.55

# Traffic tier (Tranco)
_TRAFFIC_TTL = 7 * 24 * 3600.0  # Tranco updates daily; a week-old snapshot is still fine
_TRAFFIC_TOP_N = 69_420        # bound memory; below this rank we just stay neutral
_TRAFFIC_RETRY_COOLDOWN_S = 3600.0  # if the download fails, don't hammer it every request

_traffic_ranks: "dict[str, int] | None" = None
_traffic_loaded_at = 0.0
_traffic_lock = asyncio.Lock()


def _load_traffic_ranks_sync() -> "dict[str, int]":
    """Blocking: fetch (or reuse the disk-cached) Tranco top-1M list.
    Uses `tranco` package for caching and daily-refresh bookkeeping.
    """
    import urllib3
    from tranco import Tranco
    
    # Suppress the InsecureRequestWarning when disabling SSL verification
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    t = Tranco(cache=True, cache_dir=".tranco_cache")
    t.session.verify = False  # Bypass SSL cert verification failure
    latest = t.list()
    return {domain: i for i, domain in enumerate(latest.top(_TRAFFIC_TOP_N), start=1)}


async def ensure_loaded() -> None:
    """TTL-cached, off-thread load with failure backoff."""
    global _traffic_ranks, _traffic_loaded_at
    now = time.monotonic()
    if _traffic_ranks is not None and (now - _traffic_loaded_at) < _TRAFFIC_TTL:
        return
    async with _traffic_lock:
        now = time.monotonic()
        if _traffic_ranks is not None and (now - _traffic_loaded_at) < _TRAFFIC_TTL:
            return
        try:
            _traffic_ranks = await asyncio.to_thread(_load_traffic_ranks_sync)
            _traffic_loaded_at = now
            _log.info("Loaded Tranco traffic ranks for %d domains", len(_traffic_ranks))
        except Exception:
            _log.warning("Tranco traffic list load failed; traffic boost neutral this cycle", exc_info=True)
            if _traffic_ranks is None:
                _traffic_ranks = {}
            _traffic_loaded_at = now - _TRAFFIC_TTL + _TRAFFIC_RETRY_COOLDOWN_S


def _registrable_domain(host: str) -> str:
    """Naive eTLD+1 (no public-suffix-list handling, good enough for our use)."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _is_tier1(host: str) -> bool:
    if any(host.endswith(suf) for suf in _TIER1_SUFFIXES):
        return True
    reg = _registrable_domain(host)
    return reg in _TIER1_DOMAINS or host in _TIER1_DOMAINS


def _traffic_rank(host: str) -> "int | None":
    if not _traffic_ranks:
        return None
    return _traffic_ranks.get(host) or _traffic_ranks.get(_registrable_domain(host))


def _traffic_multiplier(host: str) -> float:
    rank = _traffic_rank(host)
    if rank is None:
        return 1.0  # unranked: neutral, not penalized -- long-tail legitimate sites exist too
    if rank <= 10_000:
        return 1.25
    if rank <= 50_000:
        return 1.15
    if rank <= _TRAFFIC_TOP_N:
        return 1.05
    return 1.0


def _is_keyword_stuffed(url: str, query_terms: "set[str]") -> bool:
    """Flag URLs whose path mimics the query as a slug (anti-SEO)."""
    if not query_terms:
        return False
    path = urlparse(url).path.strip("/").replace("-", " ").replace("_", " ").lower()
    slug_words = {w for w in path.split() if len(w) > 2}
    if len(slug_words) < 3:
        return False
    overlap = len(slug_words & query_terms) / len(query_terms)
    return overlap >= _SLUG_STUFFING_THRESHOLD


def trust_multiplier(url: str, query_terms: "set[str]" = frozenset()) -> float:
    """Combine trust metrics into a single multiplier for relevance scores."""
    host = (urlparse(url).hostname or "").lower()

    mult = _TIER1_MULTIPLIER if _is_tier1(host) else _traffic_multiplier(host)

    if any(host.endswith(tld) for tld in _SUSPICIOUS_TLDS):
        mult *= _SUSPICIOUS_TLD_MULTIPLIER

    if _is_keyword_stuffed(url, query_terms):
        mult *= _SLUG_STUFFING_MULTIPLIER

    return mult
