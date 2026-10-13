from urllib.parse import urlparse

_MAX_CHARS = 20000
_MIN_CONTENT_CHARS = 250

_SKIP_DOMAINS = {
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "facebook.com",
}

_BLOCK_MARKERS = (
    "just a moment",
    "enable javascript and cookies to continue",
    "target url returned error 403",
    "access denied",
)


def skip(url: str, allowed: "frozenset[str]" = frozenset()) -> bool:
    """Reject social/login-heavy hosts that rarely provide usable article text."""
    try:
        host = (urlparse(url).hostname or "").lower()
        if any(host == domain or host.endswith("." + domain) for domain in allowed):
            return False
        return any(host == domain or host.endswith("." + domain) for domain in _SKIP_DOMAINS)
    except Exception:
        return False


def truncate(text: str, max_chars: int = _MAX_CHARS) -> str:
    """Bound a page body while preferring a sentence boundary near the limit."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(". ", 1)
    return (cut[0] + ".") if len(cut) > 1 else text[:max_chars]


def content_is_usable(text: str) -> bool:
    """Identify page bodies worth sending to the model or preserving as partials."""
    cleaned = (text or "").strip()
    if len(cleaned) < _MIN_CONTENT_CHARS:
        return False
    lowered = cleaned[:2000].lower()
    return not any(marker in lowered for marker in _BLOCK_MARKERS)
