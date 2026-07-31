import json
import logging
import os
import re
import time
from collections import OrderedDict
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

# Tier 1 — AUTHORITATIVE (×1.35)
_TIER1_SUFFIXES = (".gov", ".edu", ".org", "fandom.com", ".ac.uk", ".ac.jp", ".wiki")
_TIER1_MULTIPLIER = 1.35


# Tier 2 — REPUTABLE (×1.12)
_TIER2_SUFFIXES = (".net", ".io", ".dev", ".co.uk")
_TIER2_MULTIPLIER = 1.12

# Denylist — BLOCKED (score = 0.0)
_DENYLIST = frozenset({
    "zathong.com",
    "league-voice.org",
    "quotesgamma.com",
    "burningforsuccess.com",
    "dumbpasswords.com",
    "listchallenges.com",
    "ranker.com",
    "answers.com",
    "reference.com",
    "ask.com",
})

# Scoring penalties (used only in trust_multiplier)
_SUSPICIOUS_TLDS = (".xyz", ".top", ".click", ".buzz", ".cfd", ".cyou", ".sbs", ".rest", ".icu", ".vip")
_SUSPICIOUS_TLD_MULTIPLIER = 0.85

_FREE_HOST_PATTERNS = (
    ".blogspot.", ".blogger.", ".wordpress.com",
    ".wixsite.com", ".weebly.com", ".squarespace.com",
    ".tumblr.com", ".livejournal.com",
    ".sites.google.com",
)
_FREE_HOST_MULTIPLIER = 0.75

# Pre-fetch URL patterns (used in is_trash_url to hard-block before fetch)
_FARM_PATH_RE = re.compile(
    r"/(top-\d+[-–]|best-\d+[-–]|\d+-things[-–]|\d+-ways[-–]|\d+-tips[-–]"
    r"|ultimate-guide-to-|everything-you-need-to-know|what-is-a-|how-to-[a-z]+-in-\d+-)",
    re.IGNORECASE,
)
_HYPHEN_DENSE_RE = re.compile(r"/[a-z0-9]+(?:-[a-z0-9]+){7,}")
_QUOTE_FARM_PATH_RE = re.compile(
    r"/[\w-]*-(quotes|sayings|captions|slogans|lines|phrases|status|wishes)[-/]",
    re.IGNORECASE,
)

# Content quality patterns (used in content_quality_ok post-fetch)
_AD_MARKERS = re.compile(
    r"\b("
    r"sponsored|advertisement|advertise with us|affiliate link|affiliate disclosure"
    r"|buy now|shop now|order now|add to cart|limited time offer"
    r"|click here to|sign up for free|subscribe now|free trial"
    r"|discount code|coupon code|promo code|use code"
    r"|earn commission|we may earn|partner links"
    r")\b",
    re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:\d{1,3}[.)]\s|[-•*]\s|>\s)", re.MULTILINE)
_QUOTED_STR_RE = re.compile(r'[""\u201c][^""\u201d]{10,200}[""\u201d]')
_FILLER_PHRASES = re.compile(
    r"\b("
    r"this quote (?:captures|teaches|reminds|emphasizes|shows|highlights|speaks|is about|serves)"
    r"|the essence of this"
    r"|let.s (?:strive|embrace|not forget|stay|remember|take)"
    r"|it.s important to|we should|we too have|similarly.? we"
    r"|this (?:declaration|statement|saying|line|phrase) (?:speaks|shows|is|captures|teaches)"
    r")\b",
    re.IGNORECASE,
)


# Internal helpers
def _registrable_domain(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host

def _is_tier1(host: str) -> bool:
    return any(host.endswith(suf) for suf in _TIER1_SUFFIXES)

def _is_tier2(host: str) -> bool:
    return any(host.endswith(suf) for suf in _TIER2_SUFFIXES)

def _is_denied(host: str) -> bool:
    reg = _registrable_domain(host)
    return reg in _DENYLIST or host in _DENYLIST

def _is_trusted(host: str) -> bool:
    return _is_tier1(host) or _is_tier2(host)


# Public: trust_multiplier — scoring for search result ranking
def trust_multiplier(url: str) -> float:
    """Multiplier for relevance scores: >1 boosts, <1 penalises, 0 = drop."""
    host = (urlparse(url).hostname or "").lower()
    if _is_denied(host):
        return 0.0
    if _is_tier1(host):
        mult = _TIER1_MULTIPLIER
    elif _is_tier2(host):
        mult = _TIER2_MULTIPLIER
    else:
        mult = 1.0
    if any(host.endswith(tld) for tld in _SUSPICIOUS_TLDS):
        mult *= _SUSPICIOUS_TLD_MULTIPLIER
    if any(pat in url for pat in _FREE_HOST_PATTERNS):
        mult *= _FREE_HOST_MULTIPLIER
    return mult


# Public: is_trash_url — pre-fetch URL filter (hard-blocks before fetch)
def is_trash_url(url: str) -> bool:
    """Kill obviously garbage URLs before they waste a fetch slot."""
    host = (urlparse(url).hostname or "").lower()
    if not host or _is_trusted(host):
        return False
    path = urlparse(url).path
    return bool(
        _QUOTE_FARM_PATH_RE.search(path)
        or _HYPHEN_DENSE_RE.search(path)
        or _FARM_PATH_RE.search(path)
    )


# Public: content_quality_ok — post-fetch content gate
def content_quality_ok(text: str, url: str = "") -> tuple[bool, str]:
    """Fast heuristic quality gate on already-fetched content."""
    if not text or len(text) < 100:
        return False, "too_short"

    text_len = len(text)
    host = (urlparse(url).hostname or "").lower() if url else ""

    # Ad / affiliate density
    ad_hits = len(_AD_MARKERS.findall(text))
    if ad_hits / max(1, text_len / 1000) >= 5.0:
        return False, "ad_heavy"

    # Quote farm detection (content-based, for URLs that slipped past is_trash_url)
    if not host or not _is_trusted(host):
        quoted = len(_QUOTED_STR_RE.findall(text))
        filler = len(_FILLER_PHRASES.findall(text))
        quote_density = quoted / max(1, text_len / 1000)

        if quote_density >= 4.0 and filler >= 5:
            return False, "quote_farm"

        lines = text.split("\n")
        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) >= 8:
            short_list = [ln for ln in non_empty if _LIST_ITEM_RE.match(ln) and len(ln.strip()) < 150]
            narrative = [ln for ln in non_empty if not _LIST_ITEM_RE.match(ln) and len(ln.strip()) >= 60]
            if len(short_list) / len(non_empty) >= 0.60 and len(narrative) / len(non_empty) < 0.15:
                return False, "quote_farm"

    # Repetition ratio
    sentences = [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > 15]
    if len(sentences) >= 6:
        unique = set(sentences)
        if 1.0 - len(unique) / len(sentences) > 0.40:
            return False, "repetitive"
        if sum(len(s) for s in unique) < 200:
            return False, "thin_content"

    return True, ""


# Runtime domain learning — auto-blocks repeat offenders
_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), ".tranco_cache")
_PERSIST_PATH = os.path.join(_PERSIST_DIR, "domain_learning.json")

_BLOCK_THRESHOLD = 3
_INITIAL_BLOCK = 3600.0
_MAX_BLOCK = 86400.0
_STALE = 172800.0
_PERSIST_EVERY = 10


class _BoundedLRU(OrderedDict):
    def __init__(self, maxsize: int = 5000):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)

    def get(self, key, default=None):
        if key in self:
            self.move_to_end(key)
            return super().__getitem__(key)
        return default


class _DomainTracker:
    def __init__(self):
        self._data: _BoundedLRU = _BoundedLRU()
        self._writes = 0
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PERSIST_PATH):
                with open(_PERSIST_PATH, "r") as f:
                    raw = json.load(f)
                now = time.time()
                for domain, entry in raw.items():
                    if now - entry.get("last", 0) < _STALE:
                        self._data[domain] = entry
                _log.info("Loaded runtime domain stats for %d domains", len(self._data))
        except Exception:
            _log.debug("Could not load domain learning data", exc_info=True)

    def _persist(self):
        self._writes += 1
        if self._writes % _PERSIST_EVERY != 0:
            return
        try:
            os.makedirs(_PERSIST_DIR, exist_ok=True)
            with open(_PERSIST_PATH, "w") as f:
                json.dump(dict(self._data), f, separators=(",", ":"))
        except Exception:
            _log.debug("Could not persist domain learning data", exc_info=True)

    def _entry(self, domain: str) -> dict:
        e = self._data.get(domain)
        now = time.time()
        if e is None:
            e = {"ok": 0, "bad": 0, "last": now, "blocked_until": 0.0, "block_dur": _INITIAL_BLOCK}
            self._data[domain] = e
        elif now - e.get("last", 0) > _STALE:
            e.update({"ok": 0, "bad": 0, "last": now, "blocked_until": 0.0, "block_dur": _INITIAL_BLOCK})
        return e

    def record(self, url: str, accepted: bool):
        host = (urlparse(url).hostname or "").lower()
        if not host or _is_trusted(host):
            return
        domain = _registrable_domain(host)
        e = self._entry(domain)
        e["last"] = time.time()

        if accepted:
            e["ok"] += 1
            if e["bad"] > 0:
                e["bad"] = 0
                e["blocked_until"] = 0.0
                e["block_dur"] = _INITIAL_BLOCK
        else:
            e["bad"] += 1
            if e["bad"] >= _BLOCK_THRESHOLD and e["ok"] == 0:
                dur = min(e.get("block_dur", _INITIAL_BLOCK), _MAX_BLOCK)
                e["blocked_until"] = time.time() + dur
                e["block_dur"] = min(dur * 2, _MAX_BLOCK)
                _log.info("Runtime-blocked %s for %.0fs (bad=%d)", domain, dur, e["bad"])
        self._persist()

    def is_blocked(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        e = self._data.get(_registrable_domain(host))
        if e is None:
            return False
        now = time.time()
        return now - e.get("last", 0) < _STALE and now < e.get("blocked_until", 0.0)


_tracker = _DomainTracker()


def is_runtime_blocked(url: str) -> bool:
    return _tracker.is_blocked(url)

def record_outcome(url: str, accepted: bool) -> None:
    _tracker.record(url, accepted)

async def ensure_loaded() -> None:
    """No-op stub kept for call-site compatibility."""
    pass
