import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime

from app.config import load_config

from . import domain_trust
from .cache import _NEGATIVE_CACHE_TTL, _cache_get, _cache_set
from .embedder import warmup_embedder
from .engines import (
    _exa_search,
    _firecrawl_scrape,
    _firecrawl_search,
    _tavily_search,
    shutdown_engines,
)

from .fetcher import content_is_usable, skip, truncate
from .llm_processing import _REGEX_INTENTS, _rerank, _rewrite_query

_log = logging.getLogger(__name__)
_cfg = load_config()

_MAX_URLS = min(5, max(3, int(_cfg.get("defaults", {}).get("max_search_urls", 5))))
_HARD_TIMEOUT_SECONDS = 15.0
_WORK_TIMEOUT_SECONDS = 14.5
_REWRITE_TIMEOUT_SECONDS = 1.5
_EXA_TIMEOUT_SECONDS = 2.5
_TAVILY_TIMEOUT_SECONDS = 4.5
_FIRECRAWL_CONCURRENCY = 2


async def warmup() -> None:
    """Warm only local ranking resources; search providers need no startup probe."""
    try:
        await warmup_embedder()
    except Exception:
        _log.debug("Search embedder warmup failed", exc_info=True)


async def shutdown() -> None:
    await shutdown_engines()


def _clean(results: list[dict]) -> list[dict]:
    """Drop invalid, duplicate, blocked, and low-value URLs."""
    cleaned: list[dict] = []
    seen: set[str] = set()
    for result in results:
        url = (result.get("url") or "").strip()
        if (
            not url
            or url in seen
            or skip(url)
            or domain_trust.is_runtime_blocked(url)
            or domain_trust.is_trash_url(url)
        ):
            continue
        seen.add(url)
        result["url"] = url
        cleaned.append(result)
    return cleaned


def _usable_count(results: list[dict]) -> int:
    return sum(content_is_usable(result.get("content", "")) for result in results)


def _merge_results(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge provider results by URL, keeping the strongest available page body."""
    merged = list(existing)
    positions = {result["url"]: index for index, result in enumerate(merged)}
    for candidate in incoming:
        url = candidate["url"]
        index = positions.get(url)
        if index is None:
            positions[url] = len(merged)
            merged.append(candidate)
            continue

        current = merged[index]
        if content_is_usable(candidate.get("content", "")) and not content_is_usable(
            current.get("content", "")
        ):
            current["content"] = candidate.get("content", "")
            current["content_provider"] = candidate.get("content_provider", "provider")
        if not current.get("title") and candidate.get("title"):
            current["title"] = candidate["title"]
        if not current.get("snippet") and candidate.get("snippet"):
            current["snippet"] = candidate["snippet"]
        current["score"] = max(float(current.get("score", 0.0)), float(candidate.get("score", 0.0)))
    return merged


async def _call_search_provider(label: str, factory, timeout: float, deadline: float) -> list[dict]:
    remaining = deadline - time.monotonic()
    budget = min(timeout, remaining)
    if budget < 0.1:
        return []
    try:
        return await asyncio.wait_for(factory(), timeout=budget)
    except asyncio.TimeoutError:
        _log.warning("%s exceeded its %.2fs pipeline budget", label, budget)
        return []
    except Exception:
        _log.exception("%s failed unexpectedly", label)
        return []


async def _repair_with_firecrawl(
    results: list[dict], target: int, deadline: float
) -> tuple[list[dict], int]:
    """Scrape only enough known URLs to fill missing content slots."""
    needed = max(0, target - _usable_count(results))
    candidates = [
        result for result in results if not content_is_usable(result.get("content", ""))
    ][:needed]
    repaired = 0

    for offset in range(0, len(candidates), _FIRECRAWL_CONCURRENCY):
        remaining = deadline - time.monotonic()
        if remaining < 1.0:
            break

        batch = candidates[offset : offset + _FIRECRAWL_CONCURRENCY]
        request_timeout = min(6.5, max(1.0, remaining - 0.15))
        tasks = {
            asyncio.create_task(
                _firecrawl_scrape(result["url"], timeout_ms=int(request_timeout * 1000))
            ): result
            for result in batch
        }
        done, pending = await asyncio.wait(tasks, timeout=request_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            try:
                content = task.result()
            except Exception:
                _log.debug("Firecrawl repair task failed", exc_info=True)
                continue
            if content_is_usable(content):
                result = tasks[task]
                result["content"] = truncate(content)
                result["content_provider"] = "firecrawl"
                repaired += 1

        if _usable_count(results) >= target:
            break

    return results, repaired


async def _provider_search_cascade(
    query: str, max_results: int, deadline: float
) -> tuple[list[dict], str]:
    """Run Tavily, Exa, then Firecrawl sequentially under one deadline."""
    target = min(5, max(3, max_results))
    fallback_threshold = 3
    providers: list[str] = []

    providers.append("Tavily")
    tavily = await _call_search_provider(
        "Tavily",
        lambda: _tavily_search(query, max_results=target),
        _TAVILY_TIMEOUT_SECONDS,
        deadline,
    )
    results = _clean(tavily)

    if _usable_count(results) < fallback_threshold:
        providers.append("Exa")
        missing = max(1, target - _usable_count(results))
        exa = await _call_search_provider(
            "Exa",
            lambda: _exa_search(query, max_results=missing),
            _EXA_TIMEOUT_SECONDS,
            deadline,
        )
        results = _merge_results(results, _clean(exa))

    if _usable_count(results) < fallback_threshold and (deadline - time.monotonic()) >= 1.0:
        if results:
            has_incomplete_page = any(
                not content_is_usable(result.get("content", "")) for result in results
            )
            if has_incomplete_page:
                providers.append("Firecrawl Repair")
                results, _ = await _repair_with_firecrawl(results, target, deadline)
        else:
            providers.append("Firecrawl")
            remaining = deadline - time.monotonic()
            timeout_ms = int(max(1000, min(7000, (remaining - 0.15) * 1000)))
            firecrawl = await _call_search_provider(
                "Firecrawl",
                lambda: _firecrawl_search(query, max_results=target, timeout_ms=timeout_ms),
                remaining,
                deadline,
            )
            results = _clean(firecrawl)

    return results, " → ".join(providers)


def _make_cache_key(query: str, history_context: str, num_urls: int, chat_id: str) -> tuple:
    context_hash = hashlib.md5(history_context.encode("utf-8")).hexdigest() if history_context else ""
    return (query.lower().strip(), context_hash, num_urls, chat_id)


_inflight: "dict[tuple, asyncio.Future]" = {}


async def _run_with_hard_timeout(
    query: str, num_urls: int, history_context: str, chat_id: str, cache_key: tuple
) -> tuple[str, dict]:
    def _fail(extra: dict) -> tuple[str, dict]:
        result = (
            "",
            {
                "site": "general",
                "intent": "general",
                "original_query": query,
                "rewritten_query": query,
                "query": query,
                "fallback": True,
                "engine": "",
                "sources": [],
                **extra,
            },
        )
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result

    try:
        return await asyncio.wait_for(
            _fetch_web_context_inner(query, num_urls, history_context, chat_id),
            timeout=_HARD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _log.warning("Search hard timeout reached for %r", query)
        return _fail({"timed_out": True})
    except Exception:
        _log.exception("Search pipeline failed unexpectedly for %r", query)
        return _fail({"error": True})


async def fetch_web_context(
    query: str, num_urls: int = _MAX_URLS, history_context: str = "", chat_id: str = ""
) -> tuple[str, dict]:
    """Search and extract at most five pages, coalescing identical requests."""
    num_urls = min(5, max(3, int(num_urls)))
    cache_key = _make_cache_key(query, history_context, num_urls, chat_id)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    existing = _inflight.get(cache_key)
    if existing is not None and not existing.done():
        return await asyncio.shield(existing)

    future: "asyncio.Future" = asyncio.get_running_loop().create_future()
    _inflight[cache_key] = future
    try:
        result = await _run_with_hard_timeout(query, num_urls, history_context, chat_id, cache_key)
    except BaseException as exc:
        if not future.done():
            future.set_exception(exc)
        raise
    else:
        if not future.done():
            future.set_result(result)
        return result
    finally:
        if _inflight.get(cache_key) is future:
            del _inflight[cache_key]


async def _fetch_web_context_inner(
    query: str, num_urls: int = _MAX_URLS, history_context: str = "", chat_id: str = ""
) -> tuple[str, dict]:
    """Rewrite, search/extract, rerank, and assemble context within 14.5 seconds."""
    started = time.monotonic()
    deadline = started + _WORK_TIMEOUT_SECONDS
    cache_key = _make_cache_key(query, history_context, num_urls, chat_id)

    rewrite_started = time.monotonic()
    intent = None
    rewritten = query
    llm_entity = ""
    for pattern, pattern_intent in _REGEX_INTENTS:
        if pattern.search(query):
            intent = pattern_intent
            break

    if intent is None:
        try:
            rewrite_result = await asyncio.wait_for(
                _rewrite_query(query, history_context),
                timeout=min(_REWRITE_TIMEOUT_SECONDS, max(0.1, deadline - time.monotonic())),
            )
            rewritten = rewrite_result.get("query", query)
            intent = rewrite_result.get("intent", "general")
            llm_entity = (rewrite_result.get("entity") or "").lower().strip()
        except asyncio.TimeoutError:
            intent = "general"
            _log.debug("Query rewrite exceeded %.1fs; using the original query", _REWRITE_TIMEOUT_SECONDS)
        except Exception:
            intent = "general"
            _log.debug("Query rewrite failed; using the original query", exc_info=True)

    t_rewrite = int((time.monotonic() - rewrite_started) * 1000)
    intent = intent or "general"

    year = "" if (intent == "wiki" or re.search(r"\b(19|20)\d{2}\b", rewritten)) else str(datetime.now().year)
    site = "dictionary.cambridge.org" if intent == "dictionary" else None
    suffix = "documentation" if intent == "documentation" else ""
    wiki_suffix = "wiki" if intent == "wiki" else ""
    search_query = " ".join(part for part in (rewritten, suffix or wiki_suffix, year) if part).strip()
    provider_query = f"site:{site} {search_query}" if site else search_query

    search_started = time.monotonic()
    results, engine_used = await _provider_search_cascade(provider_query, num_urls, deadline)
    t_search = int((time.monotonic() - search_started) * 1000)

    debug: dict = {
        "site": site or "general",
        "intent": intent,
        "original_query": query,
        "rewritten_query": rewritten,
        "query": search_query,
        "fallback": "→" in engine_used,
        "engine": engine_used,
        "sources": [],
        "t_rewrite": t_rewrite,
        "t_search": t_search,
        "deadline_ms": int(_HARD_TIMEOUT_SECONDS * 1000),
    }

    if not results:
        result = ("", debug)
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result

    if llm_entity:
        anchor = llm_entity
    else:
        noise_words = {
            "wiki", "the", "and", "for", "with", "from", "site", "of", "in", "on", "at", "to",
            "list", "what", "who", "when", "where", "why", "how", "show", "give", "tell", "all",
            "about", "best", "top", "is", "are", "was", "were",
        }
        words = search_query.split()
        capitalized_spans: list[str] = []
        current_span: list[str] = []
        for word in words:
            if word[:1].isupper() and word.lower() not in noise_words and len(word) > 1:
                current_span.append(word.lower())
            else:
                if current_span:
                    capitalized_spans.append(" ".join(current_span))
                    current_span = []
        if current_span:
            capitalized_spans.append(" ".join(current_span))
        candidates = [
            word.lower()
            for word in words
            if len(word) > 1 and word.lower() not in noise_words and not word.isdigit()
        ]
        anchor = max(capitalized_spans, key=len) if capitalized_spans else max(candidates, key=len, default="")

    anchor_words = {word for word in anchor.split() if word}

    def _anchor_match(text: str) -> bool:
        lowered = (text or "").lower()
        return bool(anchor and anchor in lowered) or any(word in lowered for word in anchor_words)

    if intent == "wiki" and anchor and len(anchor) > 2:
        on_entity = [
            result
            for result in results
            if _anchor_match(result["url"]) or _anchor_match(result.get("snippet", ""))
        ]
        if on_entity:
            debug["entity_dropped"] = len(results) - len(on_entity)
            results = on_entity

    def _is_junk(url: str) -> bool:
        lowered = url.lower()
        return any(namespace in lowered for namespace in ("category:", "talk:", "file:", "special:", "user:", "/category"))

    def _priority(result: dict) -> tuple:
        url = result["url"].lower()
        if _is_junk(url):
            return (3, 0.0)
        if anchor and not _anchor_match(url):
            return (2, 0.0)
        base = 0 if ("wiki" in url or ".org" in url) else 1
        return (base, -domain_trust.trust_multiplier(result["url"]))

    terms = [
        word.lower()
        for word in search_query.split()
        if len(word) > 3
        and not word.isdigit()
        and word.lower() not in {"wiki", "documentation", "reddit", "guide"}
    ]
    threshold = max(1, len(terms) // 3)

    def _relevant(content: str, score: float = 0.0) -> bool:
        if score > 0.6 or not terms:
            return True
        lowered = content.lower()
        if anchor and not _anchor_match(lowered):
            return False
        return sum(term in lowered for term in terms) >= threshold

    rerank_started = time.monotonic()
    reranked = False
    remaining = deadline - time.monotonic()
    rerank_budget = min(1.0, max(0.0, remaining))
    debug["rerank_budget_ms"] = int(rerank_budget * 1000)
    if len(results) > 1 and rerank_budget >= 0.1:
        try:
            reranked = await asyncio.wait_for(_rerank(rewritten, results), timeout=rerank_budget)
        except asyncio.TimeoutError:
            _log.debug("Semantic reranking timed out; using heuristic order")
        except Exception:
            _log.debug("Semantic reranking failed; using heuristic order", exc_info=True)

    if reranked:
        debug["rerank"] = "embed"
        for result in results:
            result["score"] = float(result.get("score", 0.0)) * domain_trust.trust_multiplier(result["url"])
        results.sort(key=lambda result: (_is_junk(result["url"]), -float(result.get("score", 0.0))))
    else:
        debug["rerank"] = "heuristic"
        results.sort(key=_priority)
    debug["t_rerank"] = int((time.monotonic() - rerank_started) * 1000)

    parts: list[str] = []
    rejected: list[tuple[dict, str, str]] = []
    used_urls: set[str] = set()
    for result in results:
        if len(parts) >= num_urls:
            break
        content = truncate((result.get("content") or "").strip())
        if not content_is_usable(content):
            continue
        method = result.get("content_provider", "provider")
        relevant = _relevant(content, float(result.get("score", 0.0)))
        quality_ok, quality_reason = domain_trust.content_quality_ok(content, result["url"])
        accepted = relevant and quality_ok
        debug["sources"].append(
            {
                "url": result["url"],
                "method": method,
                "chars": len(content),
                "relevant": accepted,
                "score": round(float(result.get("score", 0.0)), 3),
                "quality_reject": quality_reason or None,
            }
        )
        domain_trust.record_outcome(result["url"], accepted)
        if accepted:
            parts.append(f"Source: {result['url']}\n{content}")
            used_urls.add(result["url"])
        elif quality_ok:
            rejected.append((result, content, method))

    debug["tier1_count"] = len(parts)
    debug["tier2_anchor_rescue"] = 0
    debug["tier2_score_rescue"] = 0

    for result, content, _method in rejected:
        if len(parts) >= num_urls:
            break
        if result["url"] in used_urls:
            continue
        has_anchor = not anchor or _anchor_match(content)
        high_score = float(result.get("score", 0.0)) > 0.4
        if has_anchor or high_score:
            key = "tier2_anchor_rescue" if has_anchor else "tier2_score_rescue"
            debug[key] += 1
            parts.append(f"Source: {result['url']}\n{content}")
            used_urls.add(result["url"])

    if debug["tier2_anchor_rescue"] or debug["tier2_score_rescue"]:
        debug["degraded"] = "relaxed"

    if len(parts) < num_urls:
        snippet_candidates = [
            (result, (result.get("snippet") or result.get("title") or "").strip())
            for result in results
            if result["url"] not in used_urls
        ]
        snippet_candidates = [(result, snippet) for result, snippet in snippet_candidates if len(snippet) >= 40]
        preferred = [
            pair
            for pair in snippet_candidates
            if not anchor or _anchor_match(pair[1]) or float(pair[0].get("score", 0.0)) > 0.4
        ]
        for result, snippet in preferred or snippet_candidates:
            if len(parts) >= num_urls:
                break
            parts.append(f"Source: {result['url']}\n{snippet}")
            used_urls.add(result["url"])
            debug["sources"].append(
                {
                    "url": result["url"],
                    "method": "snippet",
                    "chars": len(snippet),
                    "relevant": True,
                    "score": round(float(result.get("score", 0.0)), 3),
                    "quality_reject": None,
                }
            )
        if len(parts) > debug["tier1_count"] + debug["tier2_anchor_rescue"] + debug["tier2_score_rescue"]:
            debug["degraded"] = debug.get("degraded", "snippet")

    debug["t_fetch_wave1"] = 0
    if not parts:
        result = ("", debug)
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result

    max_total_chars = 40000
    weights = [0.30, 0.30, 0.30, 0.05, 0.05][: len(parts)]
    weight_sum = sum(weights)
    budgets = [int(max_total_chars * (weight / weight_sum)) for weight in weights]
    truncated_parts = [
        part[:budget] + "\n... [truncated to fit context window]" if len(part) > budget else part
        for part, budget in zip(parts, budgets)
    ]
    context = (
        "=== Web Search Results ===\n\n"
        + "\n\n---\n\n".join(truncated_parts)
        + "\n\n=== End of Web Results ==="
    )

    debug["t_total"] = int((time.monotonic() - started) * 1000)
    _log.info(
        "Search stats for %r: rewrite=%dms, providers=%dms, rerank=%dms, total=%dms; pages=%d",
        query,
        debug["t_rewrite"],
        debug["t_search"],
        debug["t_rerank"],
        debug["t_total"],
        len(parts),
    )

    result = (context, debug)
    _cache_set(cache_key, result)
    return result


def inject_web_context(messages: list[dict], web_ctx: str) -> None:
    """Append web context and citation instructions to the system message."""
    if not web_ctx:
        return

    suffix = (
        f"\n\n{web_ctx}\n\n"
        "Use the search results above to answer accurately. "
        "Cite specific claims inline by enclosing the URL in angle brackets, exactly like this: (Source: <https://...>). "
        "If sources conflict, note the disagreement. "
        "Do not fabricate information not found in the results.\n"
        "CRITICAL INSTRUCTION: You MUST reply in the exact same language as the user's latest query, even if the search results are in a different language."
    )

    if messages and messages[0]["role"] == "system":
        messages[0]["content"] += suffix
    else:
        messages.insert(0, {"role": "system", "content": suffix.lstrip()})
