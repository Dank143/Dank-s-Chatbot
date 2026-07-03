import asyncio
import time
import logging
import re
import hashlib
from datetime import datetime

from config import load_config
from .fetcher import fetch_content, skip, warmup_jina, shutdown_fetchers
from .cache import _cache_get, _cache_set, _NEGATIVE_CACHE_TTL
from .engines import _searxng_search, _ddg_search, _tavily_search, _FANDOM_ALLOW, shutdown_engines
from .llm_processing import _rewrite_query, _rerank, _REGEX_INTENTS
from .embedder import warmup_embedder
_log = logging.getLogger(__name__)
_cfg = load_config()

_MAX_URLS = _cfg.get("defaults", {}).get("max_search_urls", 5)

_warmup_started = False
_warmup_done = asyncio.Event()


async def warmup() -> None:
    """Prime DDG/SearXNG, the browser, and the local embedder concurrently."""
    global _warmup_started
    _warmup_started = True

    async def _warmup_searxng():
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as client:
                await client.get("http://localhost:8888/search", params={"q": "wikipedia", "format": "json"})
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
    """Wait for boot warmup to finish so the first search hits a warm session."""
    if _warmup_started and not _warmup_done.is_set():
        try:
            await asyncio.wait_for(_warmup_done.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            pass


def _clean(results: list[dict]) -> list[dict]:
    """Drop skip-listed domains (youtube/social/etc, fandom.com exempted) before
    they can win a race or waste a fetch slot. DDG already filters internally;
    this closes the same gap for SearXNG/Tavily, which don't."""
    return [r for r in results if r.get("url") and not skip(r["url"], _FANDOM_ALLOW)]


async def _staggered_search_cascade(
    searxng_q: str, search_query: str, site: str | None, max_results: int,
    is_fallback: bool = False, deadline: "float | None" = None,
) -> tuple[list[dict], str]:
    """
    Run SearXNG -> DDG -> Tavily in a staggered race.
    Budget is halved if is_fallback=True, and every phase timeout is further
    clamped against `deadline` (an absolute time.monotonic() value) so a slow
    primary cascade can't starve a fallback cascade — or the fetch stage that
    runs after this — of the overall request's time budget.
    Returns (results, engine_used).
    """
    def _cap(t: float) -> float:
        if deadline is None:
            return t
        return max(0.05, min(t, deadline - time.monotonic()))

    t1 = _cap(0.5 if is_fallback else 0.75)
    searxng_task = asyncio.ensure_future(_searxng_search(searxng_q, max_results))
    
    async def _ddg_with_timeout(timeout: float):
        try:
            return await asyncio.wait_for(
                _ddg_search(search_query, site=site, max_results=max_results, allowed=_FANDOM_ALLOW),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return []
            
    ddg_task = None
    tavily_task = None
    
    # Phase 1: wait up to t1 for SearXNG
    done, pending = await asyncio.wait([searxng_task], timeout=t1)
    if searxng_task in done:
        res = _clean(searxng_task.result())
        if res: return res, "SearXNG"
    
    # Phase 2: SearXNG didn't return, launch DDG
    t_ddg = _cap(3.0 if is_fallback else 6.0)
    ddg_task = asyncio.ensure_future(_ddg_with_timeout(t_ddg))
    pending = [t for t in (searxng_task, ddg_task) if not t.done()]
    
    if pending:
        t2 = _cap(1.0 if is_fallback else 2.0)
        done, pending = await asyncio.wait(pending, timeout=t2, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            res = _clean(task.result())
            if res:
                for p in pending: p.cancel()
                return res, "SearXNG" if task == searxng_task else "DuckDuckGo"
            
    # Phase 3: Still nothing, launch Tavily
    tavily_task = asyncio.ensure_future(_tavily_search(searxng_q, max_results=max_results))
    pending = [t for t in (searxng_task, ddg_task, tavily_task) if t and not t.done()]
    
    # Explicit ceiling on this phase — previously unbounded here, relying only
    # on each engine's own internal client timeout (Tavily's httpx client is
    # 10s) as a backstop. Now it's capped against the shared request deadline
    # too, so a hung engine can't silently eat the whole remaining budget.
    while pending:
        phase3_timeout = _cap(4.0)
        if phase3_timeout <= 0.05:
            break
        done, pending = await asyncio.wait(pending, timeout=phase3_timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            break
        for task in done:
            res = _clean(task.result())
            if res:
                for p in pending: p.cancel()
                if task == searxng_task: return res, "SearXNG"
                if task == ddg_task: return res, "DuckDuckGo"
                return res, "Tavily"

    for p in pending:
        p.cancel()
    return [], ""


def _make_cache_key(query: str, history_context: str, num_urls: int, chat_id: str) -> tuple:
    ctx_hash = hashlib.md5(history_context.encode("utf-8")).hexdigest() if history_context else ""
    return (query.lower().strip(), ctx_hash, num_urls, chat_id)


# In-flight pipeline runs, keyed the same as the cache. Lets concurrent
# identical requests (e.g. several chat turns landing on the same query
# before the first one finishes and caches) share a single rewrite -> search
# -> fetch run instead of each independently paying the full cost.
_inflight: "dict[tuple, asyncio.Future]" = {}


async def _run_with_hard_timeout(
    query: str, num_urls: int, history_context: str, chat_id: str, cache_key: tuple
) -> tuple[str, dict]:
    try:
        return await asyncio.wait_for(
            _fetch_web_context_inner(query, num_urls, history_context, chat_id), timeout=20.0
        )
    except asyncio.TimeoutError:
        _log.warning("fetch_web_context hard timeout reached for %r", query)
        result = ("", {
            "site": "general", "intent": "general",
            "original_query": query, "rewritten_query": query,
            "query": query, "fallback": True,
            "engine": "", "sources": [], "timed_out": True
        })
        # Short negative-cache: a query that reliably blows the 20s ceiling
        # (e.g. a downstream outage) would otherwise re-run the full pipeline
        # — rewrite, cascade, fetch — on every single retry.
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result


async def fetch_web_context(
    query: str, num_urls: int = _MAX_URLS, history_context: str = "", chat_id: str = ""
) -> tuple[str, dict]:
    """Rewrite, route, and fetch web context with a hard ceiling.

    Concurrent calls with identical (query, history_context, num_urls,
    chat_id) are coalesced onto a single in-flight run via `_inflight`, so a
    burst of requests hitting the same not-yet-cached query only pays the
    full rewrite -> search -> fetch cost once.
    """
    cache_key = _make_cache_key(query, history_context, num_urls, chat_id)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    existing = _inflight.get(cache_key)
    if existing is not None and not existing.done():
        # Shielded: if *this* caller's own await gets cancelled, that must
        # not cancel the shared run other callers are also waiting on.
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
    """Rewrite, route, and fetch web context."""
    t_start = time.monotonic()

    # Soft deadline, ~3s under the outer 20s hard ceiling. Every downstream
    # phase (search cascade, fallback cascade, rerank, fetch loop) clamps its
    # own timeout against this so a slow early stage leaves the later stages
    # a shrinking-but-nonzero budget, instead of each stage assuming it owns
    # a fresh full-size window and collectively overrunning the hard timeout.
    deadline = t_start + 17.0

    cache_key = _make_cache_key(query, history_context, num_urls, chat_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        _log.debug("Cache hit for %r", query)
        return cached

    t_rewrite_start = time.monotonic()
    
    intent = None
    rewritten = query
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
    else:
        await _await_warmup()

    t_rewrite = int((time.monotonic() - t_rewrite_start) * 1000)

    year = "" if re.search(r"\b(19|20)\d{2}\b", rewritten) else str(datetime.now().year)

    site = None
    suffix = ""
    wiki_entity = False

    if intent == "documentation":
        suffix = "documentation"
    elif intent == "opinion":
        site = "reddit.com"
    elif intent == "dictionary":
        site = "dictionary.cambridge.org"

    seed: list[dict] = []

    if intent == "wiki":
        wiki_entity = True
        
    if site or suffix:
        parts = [p for p in (rewritten, suffix, year) if p]
        search_query = " ".join(parts)
    else:
        parts = [rewritten, "wiki" if wiki_entity and not site else "", year]
        search_query = " ".join(p for p in parts if p).strip()

    searxng_q = f"site:{site} {search_query}" if site else search_query
    
    t_search_start = time.monotonic()
    
    # Request more raw candidates than num_urls needs — the relevance gate,
    # semantic score filter, and degradation tiers downstream all thin this
    # pool out, so a target of e.g. num_urls=10 needs a wider candidate pool
    # behind it than the old fixed 10/12, or there's nothing left to backfill
    # from once low-relevance candidates get filtered out.
    primary_pool = max(10, num_urls + 5)
    fallback_pool = max(12, num_urls + 7)

    found, engine_used = await _staggered_search_cascade(
        searxng_q, search_query, site, primary_pool, deadline=deadline
    )

    seen = {r["url"] for r in seed}
    results = seed + [r for r in found if r["url"] not in seen]
    used_fallback = False

    # Only do a general fallback search when site-scoped results are thin —
    # and only if there's meaningfully more than a sliver of budget left.
    # Launching a fresh cascade with <1s of remaining deadline is wasted
    # overhead: it's virtually guaranteed to be truncated to nothing before
    # any engine can respond, so skip it and let existing results (or the
    # degradation tiers below) handle it instead.
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

    # Lead token anchors ranking to the entity so a site-scoped search can't drift.
    _noise_words = {
        "wiki", "the", "and", "for", "with", "from", "site", "of", "in", "on", "at", "to",
        "list", "what", "who", "when", "where", "why", "how", "show", "give", "tell", "all",
        "about", "best", "top", "is", "are", "was", "were"
    }
    _words_raw = search_query.split()
    # The rewrite prompt keeps the query sentence-case but preserves proper
    # noun capitalization ("Sentence case, resolve pronouns, keep proper
    # nouns"). A capitalized, non-leading token is therefore a much stronger
    # signal for "the entity this query is about" than simply the longest
    # remaining word, which can just as easily land on an unrelated long
    # common word (e.g. "documentation") instead of the actual subject.
    _capitalized = [
        w for i, w in enumerate(_words_raw)
        if i > 0 and w[:1].isupper() and w.lower() not in _noise_words and len(w) > 1
    ]
    if _capitalized:
        _anchor = max(_capitalized, key=len).lower()
    else:
        _candidates = [
            w.lower() for w in _words_raw
            if len(w) > 1 and w.lower() not in _noise_words and not w.isdigit()
        ]
        _anchor = max(_candidates, key=len, default="")

    # On entity-wiki path, drop results that don't mention the entity at all.
    if wiki_entity and _anchor and len(_anchor) > 2:
        on_entity = [
            r for r in results
            if _anchor in r["url"].lower() or _anchor in (r.get("snippet") or "").lower()
        ]
        if on_entity:
            debug["entity_dropped"] = len(results) - len(on_entity)
            results = on_entity
        # Filter seeds strictly by anchor-in-URL.
        seed = [r for r in seed if _anchor in r["url"].lower()]

    def _is_junk(url: str) -> bool:
        u = url.lower()
        return any(ns in u for ns in
                   ("category:", "talk:", "file:", "special:", "user:", "/category"))

    def _priority(r: dict) -> int:
        url = r["url"].lower()
        # Demote wiki meta/user/namespace pages — noisy vs the main article.
        if _is_junk(url):
            return 3
        # Demote pages whose path doesn't mention the entity (off-topic drift).
        if _anchor and _anchor not in url:
            return 2
        if "wiki" in url or ".org" in url:
            return 0
        return 1

    # Relevance gate: relaxed threshold, or semantic override.
    _noise = {"wiki", "documentation", "reddit", "guide"}
    _terms = [
        w.lower() for w in search_query.split()
        if len(w) > 3 and not w.isdigit() and w.lower() not in _noise
    ]
    _threshold = max(1, len(_terms) // 3)

    def _relevant(content: str, score: float = 0.0) -> bool:
        # Two independent gates; either is sufficient on its own:
        #  1. A high semantic score (>0.6) is trusted outright, bypassing the
        #     lexical checks below — a paraphrased or translated page can be
        #     highly relevant while sharing few exact terms with the query,
        #     so we don't want lexical matching to veto a strong embedding.
        #  2. Below that confidence, fall back to requiring the anchor entity
        #     plus a fraction of the query's other terms to literally appear.
        if score > 0.6:
            return True
        if not _terms:
            return True
        cl = content.lower()
        # Require the anchor entity itself to avoid generic franchise term matches.
        if _anchor and _anchor not in cl:
            return False
        return sum(t in cl for t in _terms) >= _threshold

    def _is_youtube_watch(url: str) -> bool:
        u = url.lower()
        return "youtube.com/watch" in u or "youtu.be/" in u

    async def _fetch_one(r: dict) -> tuple[dict, str, str]:
        # YouTube watch pages are JS-rendered and not worth scraping or
        # routing through Jina — title + description from the search result
        # is what we'd realistically end up extracting anyway, so use that
        # directly instead of spending a fetch race on it.
        if _is_youtube_watch(r["url"]):
            title = (r.get("title") or "").strip()
            snip = (r.get("snippet") or "").strip()
            content = f"Title: {title}\nDescription: {snip}"
            return r, content, "snippet"
        content, method = await fetch_content(r["url"], r["snippet"])
        return r, content, method

    def _accept(r: dict, content: str, method: str) -> None:
        ok = bool(content.strip()) and _relevant(content, r.get("score", 0.0))
        debug["sources"].append({
            "url": r["url"], "method": method, "chars": len(content),
            "relevant": ok, "score": round(r.get("score", 0.0), 3),
        })
        fetched.append((r, content, ok))
        if ok and len(parts) < num_urls:
            parts.append(f"Source: {r['url']}\n{content}")

    parts: list[str] = []
    fetched: list[tuple[dict, str, bool]] = []

    # Semantic Reranking and Fetching
    t_rerank_start = time.monotonic()
    
    # 1. Semantic rerank (normally ~10-50ms locally, but the embedder's
    # concurrency semaphore can queue up under load from simultaneous chat
    # requests). Time-box it against the shared deadline so a backed-up
    # embedder degrades to the heuristic sort instead of silently eating the
    # fetch stage's budget — reranking is a quality nicety, not something
    # worth trading fetch time for.
    rerank_timeout = max(0.2, min(2.0, deadline - time.monotonic()))
    try:
        reranked_ok = await asyncio.wait_for(_rerank(rewritten, results), timeout=rerank_timeout)
    except asyncio.TimeoutError:
        reranked_ok = False
        _log.debug("Semantic rerank timed out after %.2fs; using heuristic sort", rerank_timeout)

    # Fetch a wider pool than num_urls so there's material left to backfill
    # from if the strict relevance gate rejects some of the top hits.
    _fetch_pool_size = num_urls + 3

    if reranked_ok:
        debug["rerank"] = "embed"
        _high_confidence = [r for r in results if r.get("score", 0.0) >= 0.25]
        if len(_high_confidence) >= _fetch_pool_size:
            results = _high_confidence
        # else: keep the full (score-sorted) set — filtering down to fewer
        # than _fetch_pool_size candidates here would strand the degradation
        # tiers below with nothing left to backfill from, even though lower-
        # scored candidates that could still pass a relaxed tier exist.
        results.sort(key=lambda r: (_is_junk(r["url"]), -r.get("score", 0.0)))
    else:
        results.sort(key=_priority)
    debug["t_rerank"] = int((time.monotonic() - t_rerank_start) * 1000)

    t_wave1_wait = 0.0
    t_wave2_wait = 0.0
    
    # 2. Time-Boxed Hybrid Fetch Collection
    fetch_tasks = {}
    for r in results[:_fetch_pool_size]:
        fetch_tasks[r["url"]] = asyncio.ensure_future(_fetch_one(r))

    pending = set(fetch_tasks.values())
    completed_fetches = {}
    
    start_time = time.monotonic()
    # Max wait time for fetches — normally 5.0s, but clamped down when
    # rewrite/search/rerank already ate into the shared deadline, so a slow
    # early stage can't push the total past the outer 20s hard timeout.
    budget = max(0.5, min(5.0, deadline - start_time))
    
    while pending:
        elapsed = time.monotonic() - start_time
        remaining = budget - elapsed
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
                
        # Early exit: do we have enough acceptable results?
        accepted_count = sum(
            1 for u, (res_r, content, method) in completed_fetches.items()
            if bool(content.strip()) and _relevant(content, res_r.get("score", 0.0))
        )
        if accepted_count >= num_urls:
            break

    # Cancel any remaining unused tasks to free I/O
    for task in pending:
        task.cancel()

    t_wave1_wait = time.monotonic() - start_time
    
    # Process the completed fetches in strict semantic order
    for r in results:
        if len(parts) >= num_urls:
            break
        url = r["url"]
        if url in completed_fetches:
            res_r, content, method = completed_fetches[url]
            _accept(res_r, content, method)

    debug["t_fetch_wave1"] = int(t_wave1_wait * 1000)
    debug["tier1_count"] = len(parts)
    debug["tier2_anchor_rescue"] = 0
    debug["tier2_score_rescue"] = 0

    # URLs already placed into `parts` by tier 1 — every tier below must
    # dedup against this as it tops up, not just check "is parts empty".
    _used_urls = {r["url"] for r, content, ok in fetched if ok}

    # Graceful degradation: top up through looser tiers whenever tier 1
    # didn't fill the full num_urls quota — not only when it returned
    # nothing at all. A partial strict-tier hit (e.g. 3 accepted out of 5
    # requested) previously left the remaining slots permanently unfilled
    # even when looser-tier candidates were sitting right there in `fetched`.
    if len(parts) < num_urls:
        got = {r["url"]: content for r, content, _ok in fetched}
        # Tier 2: any content mentioning the anchor (relaxed threshold), or highly relevant semantically.
        for r in results[:_fetch_pool_size]:  # semantic order
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
        # Tier 3: DDG snippets as last resort (>= 40 chars).
        snips = [
            (r, (r.get("snippet") or "").strip())
            for r in results[:_fetch_pool_size] if r["url"] not in _used_urls
        ]
        snips = [(r, s) for r, s in snips if len(s) >= 40]
        on_entity = [(r, s) for r, s in snips if not _anchor or _anchor in s.lower() or r.get("score", 0.0) > 0.4]
        _tier3_added = 0
        for r, s in (on_entity or snips):
            if len(parts) >= num_urls:
                break
            parts.append(f"Source: {r['url']}\n{s}")
            _used_urls.add(r["url"])
            _tier3_added += 1
        if _tier3_added:
            debug["degraded"] = debug.get("degraded", "snippet")

    if len(parts) < num_urls:
        # Tier 4: literally any snippet or title we have. Guaranteed context if search returned *anything*.
        _tier4_added = 0
        for r in results:
            if len(parts) >= num_urls:
                break
            if r["url"] in _used_urls:
                continue
            s = (r.get("snippet") or r.get("title") or "").strip()
            if s:
                parts.append(f"Source: {r['url']}\n{s}")
                _used_urls.add(r["url"])
                _tier4_added += 1
        if _tier4_added:
            debug["degraded"] = debug.get("degraded", "any_snippet")

    if not parts:
        result = ("", debug)
        _cache_set(cache_key, result, ttl=_NEGATIVE_CACHE_TTL)
        return result

    # Enforce a hard character limit to prevent blowing out the model's context window.
    max_total_chars = 25000
    truncated_parts = []
    current_length = 0
    
    for p in parts:
        remaining = max_total_chars - current_length
        if remaining <= 0:
            break
        if len(p) > remaining:
            truncated_parts.append(p[:remaining] + "\n... [truncated to fit context window]")
            current_length += remaining
        else:
            truncated_parts.append(p)
            current_length += len(p)

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
    """Append the web context + citation instructions to the system message for prompt caching."""
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
