import asyncio
import json
import math
import re
import logging
from datetime import datetime

from config import load_config
from llm import race_models, get_client
from .cache import get_cached_config

_log = logging.getLogger(__name__)

_REGEX_INTENTS = [
    (re.compile(r'\b(traceback|pip install|error|exception|npm install|docs|documentation|api reference)\b', re.I), "documentation"),
    (re.compile(r'\b(reddit|best|vs|versus|should i|review|opinions?|recommendations?)\b', re.I), "opinion"),
    (re.compile(r'\b(meaning of|define|definition|synonym|translate|what does .* mean)\b', re.I), "dictionary"),
    (re.compile(r'\b(who is|what is|when is|where is|when did|how tall is|how old is)\b', re.I), "wiki"),
    (re.compile(r'\b(how to|latest news|news about|weather in|price of)\b', re.I), "general"),
]

async def _rewrite_query(raw: str, context: str = "") -> dict:
    """LLM-rewrite to standalone search query with intent."""
    now = datetime.now()
    system_prompt = (
        f"The current date is {now.strftime('%B')} {now.year}. "
        "Analyze the user's message and generate a standalone web search query. "
        "Sentence case, resolve pronouns, keep proper nouns. 4-10 words. "
        "Do NOT add past years to the query unless explicitly requested. "
        "Also determine the optimal search intent.\n"
        "Output a JSON object with EXACTLY two keys:\n"
        '"query": the rewritten search query string.\n'
        '"intent": one of "wiki", "documentation", "opinion", "dictionary", or "general".'
    )
    user_content = f"Conversation so far:\n{context}\n\nLatest message: {raw}\nSearch query:" if context else raw

    async def _fetch(client, model) -> dict | None:
        try:
            _log.info("Query rewrite started using model %s", model)
            resp = await client.chat.completions.create(
                model=model, max_tokens=60, temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            raw_output = (resp.choices[0].message.content or "").strip()
            _log.info("[Background] %s query rewrite completed: %r", model, raw_output)
            try:
                parsed = json.loads(raw_output)
                return {"query": parsed.get("query", raw), "intent": parsed.get("intent", "general")}
            except json.JSONDecodeError:
                m = re.search(r'\{.*\}', raw_output, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        return {"query": parsed.get("query", raw), "intent": parsed.get("intent", "general")}
                    except json.JSONDecodeError:
                        pass
                return {"query": raw_output, "intent": "general"}
        except Exception as e:
            _log.warning("Query rewrite inner error for %s: %s", model, e)
            return None

    cfg = await get_cached_config(load_config)
    nim_model = cfg.get("rewrite_model_nim")
    ollama_model = cfg.get("rewrite_model_ollama")
    
    nim_task = asyncio.create_task(_fetch(get_client("nim"), nim_model)) if nim_model else None
    ollama_task = asyncio.create_task(_fetch(get_client("ollama"), ollama_model)) if ollama_model else None

    res = await race_models(
        ollama_task, nim_task,
        timeout=4.0, logger=_log, task_name="query rewrite",
        primary_name="Ollama", backup_name="NIM"
    )
    return res if res else {"query": raw, "intent": "general"}


from .embedder import embed_texts as _fastembed_embed

async def _embed(texts: list[str], input_type: str = "") -> "list[list[float]] | None":
    """Embed texts locally via fastembed."""
    return await _fastembed_embed(texts)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def _rerank(query: str, results: list[dict]) -> bool:
    """Attach semantic score to each result; return True on success."""
    if len(results) < 2:
        return False
    snippets = [
        (f"{r.get('title', '')} {r.get('snippet', '')}".strip() or r["url"])[:512]
        for r in results
    ]
    qv, pv = await asyncio.gather(
        _embed([query], "query"), _embed(snippets, "passage")
    )
    if not qv or not pv or len(pv) != len(results):
        return False
    q = qv[0]
    for r, v in zip(results, pv):
        r["score"] = _cosine(q, v)
    return True
