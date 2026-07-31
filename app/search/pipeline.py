import asyncio
import time
import logging
import re
import hashlib
from datetime import datetime

from app.config import load_config
from .fetcher import fetch_content, skip, warmup_jina, shutdown_fetchers
from .cache import _cache_get, _cache_set, _NEGATIVE_CACHE_TTL
from .engines import _searxng_search, _ddg_search, _tavily_search, _FANDOM_ALLOW, shutdown_engines, SEARXNG_URL
from .llm_processing import _rewrite_query, _rerank, _REGEX_INTENTS
from .embedder import warmup_embedder
from . import domain_trust

_log = logging.getLogger(__name__)
_cfg = load_config()

_MAX_URLS = _cfg.get("defaults", {}).get("max_search_urls", 5)

_warmup_started = False
_warmup_done = asyncio.Event()


async def warmup() -> None:
    """Prime SearXNG, the browser, and the local embedder concurrently."""
    global _warmup_started
    _warmup_started = True

    async def _warmup_searxng():
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as client:
                await client.get(SEARXNG_URL, params={"q": "wikipedia", "format": "json"})
            _log.debug("SearXNG warmup ok")
        except Exception:
            _log.debug("SearXNG warmup failed", exc_info=True)

    await asyncio.gather(
        _warmup_searxng(),
        warmup_embedder(),
        warmup_jina(),
        return_exceptions=True,
    )
    _warmup_done.set()


async def shutdown() -> None:
    await shutdown_engines()
    await shutdown_fetchers()


async def _await_warmup() -> None:
    """Block until boot warmup finishes (max 6s)."""
    if _warmup_started and not _warmup_done.is_set():
        try:
            await asyncio.wait_for(_warmup_done.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            pass


def _clean(results: list[dict]) -> list[dict]:
    """Drop skip-listed, runtime-blocked, and trash-URL domains before they waste a fetch slot."""
    return [
        r for r in results
        if r.get("url")
        and not skip(r["url"], _FANDOM_ALLOW)
        and not domain_trust.is_runtime_blocked(r["url"])
        and not domain_trust.is_trash_url(r["url"])
    ]


async def _staggered_search_cascade(
    searxng_q: str, search_query: str, site: str | None, max_results: int,
    is_fallback: bool = False, deadline: "float | None" = None,
) -> tuple[list[dict], str]:
    """SearXNG -> DDG -> Tavily staggered race. Returns (results, engine_used)."""
    def _cap(t: float) -> float:
        if deadline is None:
            return t
        return max(0.05, min(t, deadline - time.monotonic()))

    searxng_task = asyncio.ensure_future(_searxng_search(searxng_q, max_results))

    async def _ddg_with_timeout(timeout: float):
        try:
            return await asyncio.wait_for(
                _ddg_search(search_query, site=site, max_results=max_results, allowed=_FANDOM_ALLOW),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return []

    # Phase 1: wait for SearXNG
    t1 = _cap(0.75 if is_fallback else 1.0)
    done, pending = await asyncio.wait([searxng_task], timeout=t1)
    if searxng_task in done:
        res = _clean(searxng_task.result())
        if res:
            return res, "SearXNG"

    # Phase 2: launch DDG
    t_ddg = _cap(3.0 if is_fallback else 6.0)
    ddg_task = asyncio.ensure_future(_ddg_with_timeout(t_ddg))
    pending = [t for t in (searxng_task, ddg_task) if not t.done()]

    task_names = {searxng_task: "SearXNG", ddg_task: "DuckDuckGo"}

    if pending:
        t2 = _cap(1.0 if is_fallback else 2.0)
        done, pending = await asyncio.wait(pending, timeout=t2, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            res = _clean(task.result())
            if res:
                for p in pending:
                    p.cancel()
                return res, task_names.get(task, "DuckDuckGo")

    # Phase 3: launch Tavily
    tavily_task = asyncio.ensure_future(_tavily_search(searxng_q, max_results=max_results))
    task_names[tavily_task] = "Tavily"
    pending = [t for t in (searxng_task, ddg_task, tavily_task) if not t.done()]

    while pending:
        timeout = _cap(4.0)
        if timeout <= 0.05:
            break
        done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            break
        for task in done:
            res = _clean(task.result())
            if res:
                for p in pending:
                    p.cancel()
                return res, task_names.get(task, "Tavily")

    for p in pending:
        p.cancel()
    return [], ""


def _make_cache_key(query: str, history_context: str, num_urls: int, chat_id: str) -> tuple:
    ctx_hash = hashlib.md5(history_context.encode("utf-8")).hexdigest() if history_context else ""
    return (query.lower().strip(), ctx_hash, num_urls, chat_id)


# Coalesce concurrent identical requests onto a single in-flight run
_inflight: "dict[tuple, asyncio.Future]" = {}


async def _run_with_hard_timeout(
    query: str, num_urls: int, history_context: str, chat_id: str, cache_key: tuple
) -> tuple[str, dict]:
    def _fail(extra: dict) -> tuple[str, dict]:
        result = ("", {"site": "general", "intent": "general",
                       "original_query": query, "rewritten_query": query,
                       "query": query, "fallback": True,
                       "engine": "", "sources": [], **extra})
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result
    try:
        return await asyncio.wait_for(
            _fetch_web_context_inner(query, num_urls, history_context, chat_id), timeout=20.0
        )
    except asyncio.TimeoutError:
        _log.warning("fetch_web_context hard timeout reached for %r", query)
        return _fail({"timed_out": True})
    except Exception:
        _log.exception("fetch_web_context unexpected error for %r", query)
        return _fail({"error": True})


async def fetch_web_context(
    query: str, num_urls: int = _MAX_URLS, history_context: str = "", chat_id: str = ""
) -> tuple[str, dict]:
    """Rewrite, route, and fetch web context. Coalesces identical concurrent requests."""
    cache_key = _make_cache_key(query, history_context, num_urls, chat_id)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    existing = _inflight.get(cache_key)
    if existing is not None and not existing.done():
        return await asyncio.shield(existing)

    fut: "asyncio.Future" = asyncio.get_event_loop().create_future()
    _inflight[cache_key] = fut
    try:
        result = await _run_with_hard_timeout(query, num_urls, history_context, chat_id, cache_key)
    except BaseException as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    else:
        if not fut.done():
            fut.set_result(result)
        return result
    finally:
        if _inflight.get(cache_key) is fut:
            del _inflight[cache_key]


async def _fetch_web_context_inner(
    query: str, num_urls: int = _MAX_URLS, history_context: str = "", chat_id: str = ""
) -> tuple[str, dict]:
    """Core pipeline: rewrite -> search -> rerank -> fetch -> assemble."""
    t_start = time.monotonic()
    deadline = t_start + 17.0  # Soft deadline, ~3s under the 20s hard ceiling
    cache_key = _make_cache_key(query, history_context, num_urls, chat_id)

    t_rewrite_start = time.monotonic()
    intent = None
    rewritten = query
    llm_entity = ""

    for pattern, pattern_intent in _REGEX_INTENTS:
        if pattern.search(query):
            intent = pattern_intent
            break

    if intent is None:
        rewrite_res, _ = await asyncio.gather(
            _rewrite_query(query, history_context),
            _await_warmup(),
        )
        rewritten = rewrite_res.get("query", query)
        intent = rewrite_res.get("intent", "general")
        llm_entity = rewrite_res.get("entity", "").lower().strip()
    else:
        await _await_warmup()

    t_rewrite = int((time.monotonic() - t_rewrite_start) * 1000)

    # Timeless queries: skip year suffix for wiki intent or explicit year
    year = "" if (intent == "wiki" or re.search(r"\b(19|20)\d{2}\b", rewritten)) else str(datetime.now().year)

    site = None
    suffix = ""
    wiki_entity = (intent == "wiki")

    if intent == "documentation":
        suffix = "documentation"
    elif intent == "dictionary":
        site = "dictionary.cambridge.org"

    if site or suffix:
        search_query = " ".join(p for p in (rewritten, suffix, year) if p)
    else:
        search_query = " ".join(p for p in (rewritten, "wiki" if wiki_entity else "", year) if p).strip()

    searxng_q = f"site:{site} {search_query}" if site else search_query

    t_search_start = time.monotonic()
    # Over-request to compensate for pre-fetch URL filtering (is_trash_url, skip, etc.)
    primary_pool = max(15, num_urls + 10)
    fallback_pool = max(15, num_urls + 10)

    results, engine_used = await _staggered_search_cascade(
        searxng_q, search_query, site, primary_pool, deadline=deadline
    )
    used_fallback = False

    # General fallback when site-scoped results are thin
    if len(results) < max(2, num_urls // 2) and (deadline - time.monotonic()) > 1.0:
        used_fallback = True
        seen = {r["url"] for r in results}
        general, gen_engine = await _staggered_search_cascade(
            rewritten, rewritten, None, fallback_pool, is_fallback=True, deadline=deadline
        )
        if general:
            engine_used = f"{gen_engine} (Fallback)" if engine_used else gen_engine
            results += [r for r in general if r["url"] not in seen]

    t_search = int((time.monotonic() - t_search_start) * 1000)

    debug: dict = {
        "site": site or "general",
        "intent": intent,
        "original_query": query,
        "rewritten_query": rewritten,
        "query": search_query,
        "fallback": used_fallback,
        "engine": engine_used,
        "sources": [],
        "t_rewrite": t_rewrite,
        "t_search": t_search,
    }

    if not results:
        result = ("", debug)
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result

    # --- Entity anchor extraction ---
    if llm_entity:
        _anchor = llm_entity
    else:
        _noise_words = {
            "wiki", "the", "and", "for", "with", "from", "site", "of", "in", "on", "at", "to",
            "list", "what", "who", "when", "where", "why", "how", "show", "give", "tell", "all",
            "about", "best", "top", "is", "are", "was", "were"
        }
        _words_raw = search_query.split()
        _cap_spans: list[str] = []
        _current_span: list[str] = []
        for w in _words_raw:
            if w[:1].isupper() and w.lower() not in _noise_words and len(w) > 1:
                _current_span.append(w.lower())
            else:
                if _current_span:
                    _cap_spans.append(" ".join(_current_span))
                    _current_span = []
        if _current_span:
            _cap_spans.append(" ".join(_current_span))

        if _cap_spans:
            _anchor = max(_cap_spans, key=len)
        else:
            _candidates = [
                w.lower() for w in _words_raw
                if len(w) > 1 and w.lower() not in _noise_words and not w.isdigit()
            ]
            _anchor = max(_candidates, key=len, default="")

    _anchor_words = set(_anchor.split()) if _anchor else set()
    _anchor_words.discard("")

    def _anchor_match(text: str) -> bool:
        tl = text.lower()
        if _anchor in tl:
            return True
        return any(w in tl for w in _anchor_words) if _anchor_words else False

    # Entity filter: drop results that don't mention the entity at all
    if wiki_entity and _anchor and len(_anchor) > 2:
        on_entity = [
            r for r in results
            if _anchor_match(r["url"]) or _anchor_match(r.get("snippet") or "")
        ]
        if on_entity:
            debug["entity_dropped"] = len(results) - len(on_entity)
            results = on_entity

    def _is_junk(url: str) -> bool:
        u = url.lower()
        return any(ns in u for ns in ("category:", "talk:", "file:", "special:", "user:", "/category"))

    def _priority(r: dict) -> tuple:
        url = r["url"].lower()
        if _is_junk(url):
            return (3, 0.0)
        if _anchor and not _anchor_match(url):
            return (2, 0.0)
        base = 0 if ("wiki" in url or ".org" in url) else 1
        return (base, -domain_trust.trust_multiplier(r["url"]))

    # --- Relevance gate ---
    _terms = [
        w.lower() for w in search_query.split()
        if len(w) > 3 and not w.isdigit() and w.lower() not in {"wiki", "documentation", "reddit", "guide"}
    ]
    _threshold = max(1, len(_terms) // 3)

    def _relevant(content: str, score: float = 0.0) -> bool:
        if score > 0.6 or not _terms:
            return True
        cl = content.lower()
        if _anchor and not _anchor_match(cl):
            return False
        return sum(t in cl for t in _terms) >= _threshold

    async def _fetch_one(r: dict) -> tuple[dict, str, str]:
        if "youtube.com/watch" in r["url"].lower() or "youtu.be/" in r["url"].lower():
            title = (r.get("title") or "").strip()
            snip = (r.get("snippet") or "").strip()
            return r, f"Title: {title}\nDescription: {snip}", "snippet"
        content, method = await fetch_content(r["url"], r["snippet"])
        return r, content, method

    def _accept(r: dict, content: str, method: str) -> None:
        ok = bool(content.strip()) and _relevant(content, r.get("score", 0.0))
        quality_reason = ""
        if ok:
            quality_ok, quality_reason = domain_trust.content_quality_ok(content, r["url"])
            if not quality_ok:
                ok = False
        debug["sources"].append({
            "url": r["url"], "method": method, "chars": len(content),
            "relevant": ok, "score": round(r.get("score", 0.0), 3),
            "quality_reject": quality_reason or None,
        })
        domain_trust.record_outcome(r["url"], ok)
        fetched.append((r, content, ok))
        if ok and len(parts) < num_urls:
            parts.append(f"Source: {r['url']}\n{content}")

    parts: list[str] = []
    fetched: list[tuple[dict, str, bool]] = []

    # --- Semantic reranking ---
    t_rerank_start = time.monotonic()
    rerank_timeout = max(0.5, min(2.5, deadline - time.monotonic()))
    debug["rerank_budget_ms"] = int(rerank_timeout * 1000)

    try:
        reranked_ok = await asyncio.wait_for(_rerank(rewritten, results), timeout=rerank_timeout)
        if not reranked_ok:
            _log.debug("Semantic rerank returned False; using heuristic sort")
    except asyncio.TimeoutError:
        reranked_ok = False
        _log.warning("Semantic rerank timed out after %.2fs; using heuristic sort", rerank_timeout)

    _fetch_pool_size = num_urls + 3

    if reranked_ok:
        debug["rerank"] = "embed"
        for r in results:
            r["score"] = r.get("score", 0.0) * domain_trust.trust_multiplier(r["url"])
        _high = [r for r in results if r.get("score", 0.0) >= 0.5]
        _low = [r for r in results if r.get("score", 0.0) < 0.5]
        _high.sort(key=lambda r: (_is_junk(r["url"]), -r.get("score", 0.0)))
        _low.sort(key=lambda r: (_is_junk(r["url"]), -r.get("score", 0.0)))
        results = _high + _low
    else:
        results.sort(key=_priority)

    debug["t_rerank"] = int((time.monotonic() - t_rerank_start) * 1000)

    # --- Time-boxed fetch ---
    fetch_tasks = {r["url"]: asyncio.ensure_future(_fetch_one(r)) for r in results[:_fetch_pool_size]}
    pending = set(fetch_tasks.values())
    completed_fetches = {}

    start_time = time.monotonic()
    budget = max(0.5, min(5.0, deadline - start_time))

    while pending:
        remaining = budget - (time.monotonic() - start_time)
        if remaining <= 0:
            break
        done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            break
        for task in done:
            try:
                res_r, content, method = task.result()
                completed_fetches[res_r["url"]] = (res_r, content, method)
            except Exception as e:
                _log.debug("Fetch task failed: %s", e)
        accepted_count = sum(
            1 for u, (res_r, content, method) in completed_fetches.items()
            if bool(content.strip()) and _relevant(content, res_r.get("score", 0.0))
        )
        if accepted_count >= num_urls:
            break

    for task in pending:
        task.cancel()

    t_wave1_wait = time.monotonic() - start_time

    # Process fetches in semantic order
    for r in results:
        if len(parts) >= num_urls:
            break
        if r["url"] in completed_fetches:
            res_r, content, method = completed_fetches[r["url"]]
            _accept(res_r, content, method)

    debug["t_fetch_wave1"] = int(t_wave1_wait * 1000)
    debug["tier1_count"] = len(parts)
    debug["tier2_anchor_rescue"] = 0
    debug["tier2_score_rescue"] = 0

    _used_urls = {r["url"] for r, content, ok in fetched if ok}

    # --- Degradation tiers: top up when tier 1 didn't fill quota ---
    if len(parts) < num_urls:
        got = {r["url"]: content for r, content, _ok in fetched}
        for r in results[:_fetch_pool_size]:
            if len(parts) >= num_urls:
                break
            url = r["url"]
            if url in _used_urls:
                continue
            content = got.get(url, "")
            if content.strip():
                has_anchor = not _anchor or _anchor in content.lower()
                high_score = r.get("score", 0.0) > 0.4
                if has_anchor or high_score:
                    if has_anchor:
                        debug["tier2_anchor_rescue"] += 1
                    else:
                        debug["tier2_score_rescue"] += 1
                    parts.append(f"Source: {r['url']}\n{content}")
                    _used_urls.add(url)
        if debug["tier2_anchor_rescue"] or debug["tier2_score_rescue"]:
            debug["degraded"] = "relaxed"

    if len(parts) < num_urls:
        # Tier 3+4: snippet backfill — prefer entity matches, then any snippet/title
        candidates = [
            (r, (r.get("snippet") or r.get("title") or "").strip())
            for r in results if r["url"] not in _used_urls
        ]
        candidates = [(r, s) for r, s in candidates if len(s) >= 40]
        on_entity = [(r, s) for r, s in candidates if not _anchor or _anchor in s.lower() or r.get("score", 0.0) > 0.4]
        for r, s in (on_entity or candidates):
            if len(parts) >= num_urls:
                break
            parts.append(f"Source: {r['url']}\n{s}")
            _used_urls.add(r["url"])
        if len(parts) > debug["tier1_count"] + debug["tier2_anchor_rescue"] + debug["tier2_score_rescue"]:
            debug["degraded"] = debug.get("degraded", "snippet")

    if not parts:
        result = ("", debug)
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result

    # Truncate to context window limit with weighted budget: top 3 get 30% each, rest get 5% each.
    max_total_chars = 40000
    _weights = [0.30, 0.30, 0.30, 0.05, 0.05]
    _w = _weights[:len(parts)]
    # Normalize in case we have fewer than 5 parts (e.g. 2 parts → 0.30+0.30 → scale to 1.0)
    _w_sum = sum(_w)
    _budgets = [int(max_total_chars * (w / _w_sum)) for w in _w]
    truncated_parts = [
        p[:cap] + "\n... [truncated to fit context window]" if len(p) > cap else p
        for p, cap in zip(parts, _budgets)
    ]

    ctx = (
        "=== Web Search Results ===\n\n"
        + "\n\n---\n\n".join(truncated_parts)
        + "\n\n=== End of Web Results ==="
    )

    debug["t_total"] = int((time.monotonic() - t_start) * 1000)
    _log.info(
        "Search stats for %r: rewrite=%dms, search=%dms, rerank=%dms, fetch=%dms, total=%dms | "
        "tier1=%d, t2_anchor=%d, t2_score=%d, dropped=%d",
        query, debug.get("t_rewrite", 0), debug.get("t_search", 0), debug.get("t_rerank", 0),
        debug.get("t_fetch_wave1", 0), debug.get("t_total", 0),
        debug.get("tier1_count", 0), debug.get("tier2_anchor_rescue", 0),
        debug.get("tier2_score_rescue", 0), debug.get("entity_dropped", 0)
    )

    result = (ctx, debug)
    _cache_set(cache_key, result)
    return result


def inject_web_context(messages: list[dict], web_ctx: str) -> None:
    """Append web context + citation instructions to the system message."""
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
