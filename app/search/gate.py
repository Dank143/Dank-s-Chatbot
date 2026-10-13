import asyncio
import logging

from app.config import load_config
from app.llm import race_models, get_client
from .cache import get_cached_config

_log = logging.getLogger(__name__)

async def should_search(query: str, history_context: str = "") -> bool:
    """LLM-gate to decide if a web search is needed to answer accurately."""
    system_prompt = (
        "You are an ultra-fast search-necessity classifier. Given a user message and conversation history, "
        "your ONLY job is to decide if a web search is strictly required to answer accurately.\n\n"
        "Answer YES if the query involves:\n"
        "- Specific people, characters, media (books/movies/games), or niche figures not universally known.\n"
        "- Recent events, current news, live data, prices, sports scores, or weather.\n"
        "- Obscure historical facts, highly specialized domain knowledge, or niche internet culture/slang.\n"
        "- Specific troubleshooting of obscure technical errors, new software libraries, or API documentation.\n"
        "- Anything time-sensitive or likely to have changed in the last 2 years.\n\n"
        "Answer NO if the query involves:\n"
        "- Universally known factual knowledge (e.g., WWII, gravity, how water boils, major world capitals).\n"
        "- Coding, math, or logic tasks that do not require external documentation or real-time data.\n"
        "- Creative writing, formatting, translation, summarization, or brainstorming requests.\n"
        "- Subjective opinions, ethical discussions, or philosophical questions.\n"
        "- Standard conversational greetings, small talk, or clarifications of previous messages.\n\n"
        "You MUST reply with ONLY the word \"YES\" or \"NO\". Do not explain your reasoning. Do not include punctuation."
    )
    user_content = f"Conversation so far:\n{history_context}\n\nLatest message: {query}\nSearch needed:" if history_context else f"Latest message: {query}\nSearch needed:"

    async def _fetch(client, model) -> bool | None:
        try:
            _log.info("Search gate started using model %s", model)
            resp = await client.chat.completions.create(
                model=model, max_tokens=5, temperature=0.0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            raw_output = (resp.choices[0].message.content or "").strip().upper()
            _log.info("[Background] %s search gate completed: %r", model, raw_output)
            
            # Since models may occasionally return things like "YES." or "search needed: YES",
            # we'll do a simple substring check.
            if "YES" in raw_output:
                return True
            if "NO" in raw_output:
                return False
                
            return None
        except Exception as e:
            _log.warning("Search gate inner error for %s: %s", model, e)
            return None

    cfg = await get_cached_config(load_config)
    gate_models = cfg.get("search_gate_model", {})
    nim_model = gate_models.get("nim")
    ollama_model = gate_models.get("ollama")
    cloudflare_model = gate_models.get("cloudflare")
    
    nim_task = asyncio.create_task(_fetch(get_client("nim"), nim_model)) if nim_model else None
    ollama_task = asyncio.create_task(_fetch(get_client("ollama"), ollama_model)) if ollama_model else None
    cloudflare_task = asyncio.create_task(_fetch(get_client("cloudflare"), cloudflare_model)) if cloudflare_model else None

    tasks = [t for t in (nim_task, ollama_task, cloudflare_task) if t]
    
    if not tasks:
        return False
        
    import time
    start_time = time.monotonic()
    
    yes_count = 0
    no_count = 0
    pending = set(tasks)
    
    target_yes = 2 if len(tasks) >= 3 else len(tasks)
    target_no = len(tasks) - target_yes + 1 
    
    while pending:
        elapsed = time.monotonic() - start_time
        remaining = 1.5 - elapsed
        if remaining <= 0:
            break
            
        done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        
        for t in done:
            try:
                res = t.result()
                if res is True:
                    yes_count += 1
                else:
                    no_count += 1
            except Exception:
                no_count += 1
                
        if yes_count >= target_yes:
            for t in pending:
                t.cancel()
            _log.info("Search gate consensus reached: YES (%d/%d)", yes_count, len(tasks))
            return True
        if no_count >= target_no:
            for t in pending:
                t.cancel()
            _log.info("Search gate consensus reached: NO (%d/%d)", no_count, len(tasks))
            return False
            
    for t in pending:
        t.cancel()
        
    total_answered = yes_count + no_count
    if total_answered == 1:
        ans = "YES" if yes_count == 1 else "NO"
        _log.info("Search gate timed out, but 1 model answered. Using its response: %s", ans)
        return yes_count == 1
    elif total_answered == 2:
        if yes_count == 2:
            _log.info("Search gate timed out, but 2 models agreed: YES")
            return True
        elif no_count == 2:
            _log.info("Search gate timed out, but 2 models agreed: NO")
            return False
        else:
            _log.info("Search gate timed out, 2 models disagreed. Defaults to NO.")
            return False
            
    _log.warning("Search gate timed out with 0 answers. Defaults to NO.")
    return False
