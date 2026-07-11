import asyncio
import json
import logging
import re
import time

import httpx
from openai import AsyncOpenAI
from app.config import provider_api

logger = logging.getLogger(__name__)

_client_cache: dict[tuple, AsyncOpenAI] = {}

def get_client(provider: str) -> AsyncOpenAI:
    """Get or create an AsyncOpenAI client for the given provider."""
    api = provider_api(provider)
    key = (api["key"], api["base_url"])
    if key not in _client_cache:
        _client_cache[key] = AsyncOpenAI(
            api_key=key[0],
            base_url=key[1],
            http_client=httpx.AsyncClient(
                http2=True,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
                timeout=httpx.Timeout(60.0, connect=5.0),
            ),
        )
    return _client_cache[key]


_CREATOR_KEYWORDS_EN = {"??:D??"} # {"creator", "maker", "developer", "father", "daddy"}
_CREATOR_RESPONSE_EN = "ALL HAIL MISTER DANG! WOOOOOO BABIIIIII!"

_CREATOR_PHRASES_VI = ["??:D??"] # ["tạo ra", "làm ra", "code ra", "thiết kế", "nhà sáng tạo", "cha đẻ", "ông trùm"]
_CREATOR_RESPONSE_VI = "QUÝ NGÀI ĐĂNG VĨ ĐẠI. SIUUUUUU!"


def is_asking_about_creator(text: str) -> str | None:
    """Canned hail response if the text asks who made the bot, else None."""
    if any(p in text.lower() for p in _CREATOR_PHRASES_VI):
        return _CREATOR_RESPONSE_VI
    pattern = r'\byour\s+(?:' + '|'.join(re.escape(k) for k in _CREATOR_KEYWORDS_EN) + r')\b'
    if re.search(pattern, text, re.IGNORECASE):
        return _CREATOR_RESPONSE_EN
    return None


async def race_models(primary_task, backup_task, timeout=5.0, logger=None, task_name="task", primary_name="Primary", backup_name="Backup"):
    """
    Run two tasks (primary and backup) with an overall timeout.
    Returns the result of primary if it succeeds.
    If primary fails or times out, returns backup if it succeeds.
    Returns None if both fail or timeout.
    """
    start_time = time.monotonic()
    pending = {t for t in (primary_task, backup_task) if t}
    log = logger or logging.getLogger(__name__)

    def _safe_result(task):
        try:
            return task.result()
        except Exception as e:
            log.warning("Task %s raised exception: %s", task, e)
            return None

    def _short_repr(val):
        s = repr(val)
        return s if len(s) < 200 else s[:197] + "..."

    while pending:
        elapsed = time.monotonic() - start_time
        remaining = timeout - elapsed
        if remaining <= 0:
            break

        done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            break

        if primary_task in done:
            res = _safe_result(primary_task)
            if res:
                log.info("%s was used for %s: %s", primary_name, task_name, _short_repr(res))
                return res
                
        if backup_task and backup_task in done:
            res = _safe_result(backup_task)
            if res:
                if primary_task in pending:
                    prim_done, _ = await asyncio.wait([primary_task], timeout=0.4)
                    if primary_task in prim_done:
                        n_res = _safe_result(primary_task)
                        if n_res:
                            log.info("%s finished in grace window and was used for %s: %s", primary_name, task_name, _short_repr(n_res))
                            return n_res
                log.info("%s timed out or failed, %s used for %s: %s", primary_name, backup_name, task_name, _short_repr(res))
                return res

    log.warning("%s fully failed or timed out.", task_name.capitalize())
    return None


def parse_attachments(raw: str | None) -> dict:
    """Parse attachments JSON into {images, documents}; legacy list → images."""
    if not raw:
        return {"images": [], "documents": []}
    data = json.loads(raw)
    if isinstance(data, list):
        return {"images": data, "documents": []}
    return {"images": data.get("images", []), "documents": data.get("documents", [])}


def build_api_content(text: str, attachments: dict) -> "str | list":
    """Build plain text or multimodal content parts for a message."""
    images = attachments.get("images", [])
    documents = attachments.get("documents", [])

    full_text = text
    if documents:
        doc_blocks = "\n\n".join(
            f"[Attached file: {d['name']}]\n{d['text']}" for d in documents
        )
        full_text = doc_blocks + ("\n\n" + text if text else "")

    if not images:
        return full_text
    parts: list[dict] = [{"type": "text", "text": full_text}] if full_text else []
    for img in images:
        parts.append({"type": "image_url", "image_url": {"url": img}})
    return parts


def _to_parts(content: "str | list") -> list[dict]:
    return content if isinstance(content, list) else [{"type": "text", "text": content}]



def reasoning_controls(reasoning: str | None) -> tuple[dict, str | None]:
    """Map a model's YAML `reasoning` tag to (extra create() kwargs, system suffix).

    Currently disabled — thinking runs freely. Uncomment the block below
    to re-enable per-family suppression (qwen, gptoss, nemotron, etc.).
    """
    # if reasoning == "qwen":
    #     return {"extra_body": {"chat_template_kwargs": {"thinking": False}}}, None
    # if reasoning == "gptoss":
    #     return {"reasoning_effort": "low"}, None
    # if reasoning == "nemotron":
    #     return {}, "detailed thinking off"
    # if reasoning == "minimax":
    #     return {"extra_body": {"thinking": {"type": "disabled"}}}, None
    # if reasoning == "kimi":
    #     return {}, "You must respond directly. Do not use extended thinking or output reasoning chains."
    # if reasoning == "glm":
    #     return {}, "You must respond directly. Do not use extended thinking or output reasoning chains."
    return {}, None


def build_messages(history, system_prompt: str | None, today: str | None = None,
                   extra_system: str | None = None) -> list[dict]:
    """Convert DB history rows into OpenAI-format messages list."""
    rows = list(history)
    # Drop leading assistant rows (truncation may start mid-exchange)
    while rows and rows[0]["role"] != "user":
        rows = rows[1:]

    last_user_idx = max(
        (i for i, r in enumerate(rows) if r["role"] == "user"),
        default=None,
    )
    raw: list[dict] = []
    for i, r in enumerate(rows):
        att = parse_attachments(r["attachments"])
        had_images = bool(att["images"])
        had_documents = bool(att["documents"])
        # Keep attachments only on the last user turn to limit prompt size.
        if i != last_user_idx:
            att["images"] = []
            att["documents"] = []
            
        raw_text = r["content"]
        # Strip <think> blocks from historical assistant replies to save massive amounts of tokens!
        if r["role"] == "assistant":
            stripped = re.sub(r"<think>.*?</think>\n?", "", raw_text, flags=re.DOTALL).strip()
            raw_text = stripped if stripped else "[Thought process omitted]"
            
        content = build_api_content(raw_text, att)
        # Substitute placeholder for empty content (stripped attachment-only turns).
        if isinstance(content, str) and not content.strip():
            content = "[image]" if had_images else "[document]" if had_documents else "[no content]"
        raw.append({"role": r["role"], "content": content})

    # merge consecutive same-role messages
    messages: list[dict] = []
    for msg in raw:
        if messages and messages[-1]["role"] == msg["role"]:
            prev, curr = messages[-1]["content"], msg["content"]
            if isinstance(prev, str) and isinstance(curr, str):
                messages[-1]["content"] = prev + "\n\n" + curr
            else:
                messages[-1]["content"] = _to_parts(prev) + _to_parts(curr)
        else:
            messages.append(msg)

    # Move `today` out of the system prompt to the end of the last user message.
    # This prevents the system prompt from changing every minute (which breaks prefix caching).
    # Phrasing it passively stops the model from randomly announcing the time.
    if today and messages and messages[-1]["role"] == "user":
        env_tag = f"\n\n[System note: Current time is {today}. Do not mention this unless relevant.]"
        if isinstance(messages[-1]["content"], str):
            messages[-1]["content"] += env_tag
        else:
            messages[-1]["content"].append({"type": "text", "text": env_tag})

    sys_parts: list[str] = []
    if extra_system:
        sys_parts.append(extra_system)
    if system_prompt:
        sys_parts.append(system_prompt)
    if sys_parts:
        messages = [{"role": "system", "content": "\n".join(sys_parts)}] + messages
    return messages


_THINK_OPEN  = "<think>"
_THINK_CLOSE = "</think>"
_CHANNEL_OPEN_RE = re.compile(r'<\|channel>[^\n]*\n?')


async def llm_stream(client, model, messages, max_tokens, temperature, result: dict,
                     extra_create: dict | None = None):
    """Stream model reply as SSE deltas, emitting <think> content separately."""
    full_content: list[str] = []
    think_content: list[str] = []
    finish_reason = None
    in_think = False
    tag_buf = ""  # holds tail chars that might be a partial tag
    raw_chunks: list[str] = []  # raw model text (pre-think-filter), for blank rescue
    t_start = time.monotonic()  # request sent
    t_first = None              # first content chunk received (time-to-first-token)
    t_think_start = None        # when thinking began

    def _flush(text: str) -> tuple[str, str]:
        """Filter text through think-tag state machine.

        Returns (visible_text, thinking_text).
        """
        nonlocal in_think, tag_buf
        s = tag_buf + text
        tag_buf = ""
        visible: list[str] = []
        thinking: list[str] = []
        while s:
            if in_think:
                idx = s.find(_THINK_CLOSE)
                if idx == -1:
                    last_lt = s.rfind("<")
                    if last_lt != -1 and len(s) - last_lt < len(_THINK_CLOSE):
                        keep = len(s) - last_lt
                        thinking.append(s[:-keep])
                        tag_buf = s[-keep:]
                    else:
                        thinking.append(s)
                        tag_buf = ""
                    break
                thinking.append(s[:idx])
                s = s[idx + len(_THINK_CLOSE):].lstrip("\n")
                in_think = False
            else:
                idx = s.find(_THINK_OPEN)
                if idx == -1:
                    last_lt = s.rfind("<")
                    if last_lt != -1 and len(s) - last_lt < len(_THINK_OPEN):
                        keep = len(s) - last_lt
                        visible.append(s[:-keep])
                        tag_buf = s[-keep:]
                    else:
                        visible.append(s)
                        tag_buf = ""
                    break
                visible.append(s[:idx])
                s = s[idx + len(_THINK_OPEN):]
                in_think = True
        return "".join(visible), "".join(thinking)

    try:
        last_exc = None
        for attempt in range(2):
            try:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **(extra_create or {}),
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta
                    
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                    if not reasoning and hasattr(delta, "model_extra") and delta.model_extra:
                        reasoning = delta.model_extra.get("reasoning_content") or delta.model_extra.get("reasoning")
                        
                    if reasoning:
                        if not isinstance(reasoning, str):
                            reasoning = str(reasoning)
                        if t_first is None:
                            t_first = time.monotonic()
                        if t_think_start is None:
                            t_think_start = time.monotonic()
                        think_content.append(reasoning)
                        yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning})}\n\n"
                    if not delta.content:
                        continue
                    
                    content_val = delta.content
                    if not isinstance(content_val, str):
                        logger.warning("llm_stream expected string for delta.content but got %s: %r", type(content_val), content_val)
                        if isinstance(content_val, dict) and "text" in content_val:
                            content_val = content_val["text"]
                        elif isinstance(content_val, list) and len(content_val) > 0 and isinstance(content_val[0], dict) and "text" in content_val[0]:
                            content_val = content_val[0]["text"]
                        else:
                            content_val = str(content_val)

                    if t_first is None:
                        t_first = time.monotonic()
                    chunk = _CHANNEL_OPEN_RE.sub(_THINK_OPEN, content_val).replace("<channel|>", _THINK_CLOSE)
                    raw_chunks.append(chunk)
                    visible, thinking = _flush(chunk)
                    if thinking:
                        if t_think_start is None:
                            t_think_start = time.monotonic()
                        think_content.append(thinking)
                        yield f"data: {json.dumps({'type': 'thinking', 'content': thinking})}\n\n"
                    if not visible:
                        continue
                    full_content.append(visible)
                    if think_content and len(full_content) == 1:
                        think_secs = round(time.monotonic() - t_think_start) if t_think_start else 0
                        yield f"data: {json.dumps({'type': 'thinking_done', 'duration': think_secs})}\n\n"
                        result["thought_time_ms"] = think_secs * 1000
                    yield f"data: {json.dumps({'type': 'delta', 'content': visible})}\n\n"
                last_exc = None
                break
            except Exception as exc:
                exc_str = str(exc)
                is_rate_limit = (
                    "429" in exc_str
                    or getattr(exc, "status_code", None) == 429
                    or "ResourceExhausted" in exc_str
                    or "resource_exhausted" in exc_str.lower()
                    or "overloaded" in exc_str.lower()
                    or "503" in exc_str
                    or getattr(exc, "status_code", None) == 503
                )
                if is_rate_limit:
                    last_exc = exc
                    break
                if attempt == 0 and not full_content:
                    logger.warning("llm_stream early-error retry model=%s: %s", model, exc)
                    finish_reason = None
                    in_think = False
                    tag_buf = ""
                    t_first = None
                    t_think_start = None
                    raw_chunks.clear()
                    think_content.clear()
                    await asyncio.sleep(0.6)
                    continue
                last_exc = exc
                break

        if last_exc is not None:
            raw_len = sum(len(c) for c in raw_chunks)
            logger.warning("llm_stream error model=%s finish=%s raw=%d: %s", model, finish_reason, raw_len, last_exc)
            is_rate_limit = (
                "429" in str(last_exc)
                or getattr(last_exc, "status_code", None) == 429
                or "ResourceExhausted" in str(last_exc)
                or "resource_exhausted" in str(last_exc).lower()
                or "overloaded" in str(last_exc).lower()
                or "503" in str(last_exc)
                or getattr(last_exc, "status_code", None) == 503
            )
            err_msg = "The model is currently overloaded — too many requests. Wait a moment then try again, or switch to another model." if is_rate_limit else str(last_exc)
            yield f"data: {json.dumps({'type': 'error', 'message': err_msg})}\n\n"
            return

        # flush any buffered tail after stream ends
        if not in_think and tag_buf.strip():
            full_content.append(tag_buf)
            yield f"data: {json.dumps({'type': 'delta', 'content': tag_buf})}\n\n"

        # If thinking ended but no visible content arrived, send thinking_done now.
        if think_content and not full_content:
            think_secs = round(time.monotonic() - t_think_start) if t_think_start else 0
            yield f"data: {json.dumps({'type': 'thinking_done', 'duration': think_secs})}\n\n"
            result["thought_time_ms"] = think_secs * 1000

        # Rescue unclosed <think>: replay raw stream if visible output is blank.
        if in_think and not "".join(full_content).strip():
            salvaged = "".join(raw_chunks).replace(_THINK_OPEN, "").replace(_THINK_CLOSE, "").strip()
            if salvaged:
                logger.warning("llm_rescue unclosed_think model=%s chars=%d", model, len(salvaged))
                full_content.append(salvaged)
                yield f"data: {json.dumps({'type': 'delta', 'content': salvaged})}\n\n"

    finally:
        visible = "".join(full_content)
        think_text = "".join(think_content)
        raw_len = sum(len(c) for c in raw_chunks)
        now = time.monotonic()
        ttft = (t_first - t_start) if t_first else (now - t_start)
        gen = (now - t_first) if t_first else 0.0
        
        log = logger.warning if (not visible.strip() and finish_reason not in ("stop", None)) else logger.info
        log(
            "llm_done model=%s finish=%s raw_chars=%d visible_chars=%d think_chars=%d unclosed_think=%s "
            "ttft=%.2fs gen=%.2fs total=%.2fs",
            model, finish_reason, raw_len, len(visible), len(think_text), in_think,
            ttft, gen, now - t_start,
        )

        saved = (f"{_THINK_OPEN}{think_text}{_THINK_CLOSE}\n" if think_text else "") + visible
        result["content"] = saved
        result["finish_reason"] = finish_reason
        result["ttfs_ms"] = round(ttft * 1000)
        result["total_ms"] = round((now - t_start) * 1000)
