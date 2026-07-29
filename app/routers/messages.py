import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import (
    load_config,
    provider_model_info,
    provider_for_model,
    get_personas,
    get_common_system_prompt,
)
from app.database import db_execute, run_db_task, now_iso
from app.search import fetch_web_context, inject_web_context
from app.llm import build_messages, is_asking_about_creator, llm_stream, reasoning_controls, race_models, get_client
from app.schemas import RegenerateBody, SaveAssistantBody, SendMessageBody

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chats")

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_SEP = r'[\s.\-…_]*'
_DANG_VI_RE = re.compile(r'[Đđ]' + _SEP + r'[Ăă]' + _SEP + r'n' + _SEP + r'g', re.IGNORECASE)
_DANG_EN_RE = re.compile(r'(?<![a-zA-Z])d' + _SEP + r'a' + _SEP + r'n' + _SEP + r'g(?![a-zA-Z])', re.IGNORECASE)


def _fallback_title(text: str) -> str:
    return text[:60].strip() + ("…" if len(text) > 60 else "")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _timing_json(result: dict) -> "str | None":
    """Extract timing data from a stream result dict, or None if absent."""
    if result and result.get("ttfs_ms") is not None and result.get("total_ms") is not None:
        p = {"ttfs_ms": result["ttfs_ms"], "total_ms": result["total_ms"]}
        if result.get("thought_time_ms") is not None:
            p["thought_time_ms"] = result["thought_time_ms"]
        return json.dumps(p)
    return None


def _resolve_model_persona(chat: dict, body, cfg: dict) -> tuple[str, str]:
    """Pick model and persona from body → chat → config defaults, respecting duo_side."""
    if body.duo_side == 1:
        model = str(body.model or chat.get("model2") or cfg.get("default_model") or "")
        persona = str(body.persona or chat.get("persona2") or "default")
    else:
        model = str(body.model or chat.get("model") or cfg.get("default_model") or "")
        persona = str(body.persona or chat.get("persona") or "default")
    return model, persona


async def _save_assistant(chat_id: str, msg_id: str, content: str, title: "str | None", model: "str | None" = None, overwrite: bool = False, duo_side: int = 0, search_data: "str | None" = None, timing_data: "str | None" = None, persona: "str | None" = None) -> None:
    """Persist an assistant message, bump the chat, and optionally set its title."""
    def _task(conn):
        ts = now_iso()
        if overwrite:
            conn.execute(
                "UPDATE messages SET content=?, model=?, duo_side=?, search_data=?, timing_data=?, persona=? WHERE id=?",
                (content, model, duo_side, search_data, timing_data, persona, msg_id)
            )
        else:
            conn.execute(
                "INSERT INTO messages (id, chat_id, role, content, created_at, model, duo_side, search_data, timing_data, persona) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (msg_id, chat_id, "assistant", content, ts, model, duo_side, search_data, timing_data, persona),
            )
        conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (ts, chat_id))
        if title:
            conn.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))
    await run_db_task(_task)


def _model_reasoning(model_id: str) -> "str | None":
    """The `reasoning` tag for a model id from models.yaml, or None if untagged."""
    info = provider_model_info(model_id)
    return info.get("reasoning") if info else None


def _build_request(history, today: str, model: str, persona: str = "default"):
    """Shared message/generation setup for send + regenerate."""
    
    # EXPERIMENT: Add more years to today. Comment when finished experimenting.
    # try:
    #     today = re.sub(r'\b20\d{2}\b', lambda m: str(int(m.group(0)) + 69), today)
    # except Exception:
    #     pass

    defaults = load_config().get("defaults", {})
    max_turns = defaults.get("max_history_turns", 50)
    if len(history) > max_turns:
        history = history[-max_turns:]
    extra_create, extra_system = reasoning_controls(_model_reasoning(model))
    # Remove asterisks used in YAML names (e.g. "Gemma 4 31B*")
    model_name = provider_model_info(model).get("name", "").replace("*", "").strip()
    model_identity = f"You are {model_name}."

    if extra_system:
        extra_system = f"{model_identity}\n{extra_system}"
    else:
        extra_system = model_identity

    personas = get_personas()
    base_prompt = get_common_system_prompt()
    persona_modifier = personas.get(persona, "")
    
    if persona_modifier:
        system_prompt = f"{base_prompt}\n\n{persona_modifier}".strip()
    else:
        system_prompt = base_prompt

    messages = build_messages(history, system_prompt, today, extra_system)
    prov = provider_for_model(model)
    return (get_client(prov), messages,
            defaults.get("max_tokens", 2048), defaults.get("temperature", 0.5), extra_create)


async def _generate_title(user_content: str, assistant_reply: str = "") -> str:
    """LLM-generate a 3-6 word chat title; falls back to truncated text."""
    cfg = load_config()
    nim_model = cfg.get("title_model_nim")
    ollama_model = cfg.get("title_model_ollama")
    
    fallback = _fallback_title(user_content)
    system = (
        "Generate a short, natural title (MINIMUM 3 words, MAXIMUM 6 words) that captures the TOPIC of what the user is asking about. "
        "Do NOT describe the message itself or the user's action. Focus on the subject matter. Use the same language as the user's prompt.\n\n"
        "Rules: no punctuation, no quotes, no explanation, capitalize ONLY the first letter and proper nouns.\n"
        "CRITICAL: Your response MUST contain at least 3 words. Single-word or two-word titles are INVALID.\n\n"
        "Examples:\n"
        "User: \"Help me debug this Python error\" → Debugging a Python error\n"
        "User: \"What's the capital of France?\" → Capital of France\n"
        "User: \"Hello\" + Assistant talks about AI → Greeting and AI chat\n"
        "User: \"hi\" → Casual greeting conversation\n"
    )
    user_parts = [user_content[:300]]
    if assistant_reply:
        user_parts.append(f"\n\nAssistant replied: {assistant_reply[:300]}")
    user = "".join(user_parts)

    async def _fetch(provider: str, model: str) -> str | None:
        try:
            logger.info("Title generation started with %s using %s", provider, model)
            client = get_client(provider)
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=50,
                temperature=0.0,
                stream=False,
            )
            raw = resp.choices[0].message.content or ""
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
            raw = re.sub(r"^(?:title|name|subject)\s*[:\-–]\s*", "", raw, flags=re.IGNORECASE)
            raw = raw.strip("\"'")
            word_count = len(raw.split())
            if not raw or not (3 <= word_count <= 12):
                logger.warning("%s generated invalid title (expected 3-12 words, got %d): %r", provider, word_count, raw)
                return None
            logger.info("[Background] %s title generation completed: %r", provider, raw)
            return raw
        except Exception as e:
            logger.warning("%s title generation inner error: %s", provider, e)
            return None

    nim_task = asyncio.create_task(_fetch("nim", nim_model)) if nim_model else None
    ollama_task = asyncio.create_task(_fetch("ollama", ollama_model)) if ollama_model else None

    res = await race_models(
        ollama_task, nim_task, 
        timeout=5.0, logger=logger, task_name="title",
        primary_name="Ollama", backup_name="NIM"
    )
    return res if res else fallback


async def _do_web_search(query: str, history: list, chat_id: str, api_messages: list) -> "tuple[str | None, str]":
    """Run web search, inject context, return (search_debug_json, search_sse_event)."""
    ctx_turns = [m for m in history if m.get("content")][:-1][-6:]
    history_context = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in ctx_turns)
    try:
        web_ctx, search_debug = await asyncio.wait_for(
            fetch_web_context(query, history_context=history_context, chat_id=chat_id), timeout=22.0
        )
    except asyncio.TimeoutError:
        web_ctx, search_debug = "", {
            "site": "general", "original_query": query,
            "rewritten_query": query, "query": query,
            "fallback": True, "sources": [], "timed_out": True,
        }
    inject_web_context(api_messages, web_ctx)
    search_payload = {'got_context': bool(web_ctx), **search_debug}
    return json.dumps(search_payload), _sse({'type': 'search_debug', **search_payload})


def _fetch_history(conn, chat_id: str, cfg: dict, duo_side: int, before_msg_id: "str | None" = None) -> list[dict]:
    """Fetch and filter chat history for a duo_side track."""
    max_turns = cfg.get("defaults", {}).get("max_history_turns", 50)
    sql_limit = max(max_turns * 4, 20)
    
    query = "SELECT role, content, attachments, duo_side FROM messages WHERE chat_id=?"
    params: list = [chat_id]
    if before_msg_id:
        target = conn.execute("SELECT created_at FROM messages WHERE id=?", (before_msg_id,)).fetchone()
        if target:
            query += " AND created_at < ?"
            params.append(target["created_at"])
    query += f" ORDER BY created_at DESC LIMIT {sql_limit}"
    
    rows = list(reversed(conn.execute(query, tuple(params)).fetchall()))
    return [dict(m) for m in rows if m["role"] == "user" or m["duo_side"] == duo_side]


@router.post("/{chat_id}/messages")
async def send_message(chat_id: str, body: SendMessageBody):
    cfg = load_config()

    images = body.images or []
    documents = [d.model_dump() for d in (body.documents or [])]
    user_msg_id = str(uuid.uuid4())

    # Normalize images: accept both plain dataUrl strings and {name, dataUrl} objects.
    normalized_images = [
        {"name": "image", "dataUrl": img} if isinstance(img, str) else img.model_dump()
        for img in images
    ]

    def _setup(conn):
        att_json = json.dumps({"images": normalized_images, "documents": documents}) if (normalized_images or documents) else None
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        chat = dict(chat)
        model, persona = _resolve_model_persona(chat, body, cfg)
        ts = now_iso()
        if not body.skip_user_save:
            conn.execute(
                "INSERT INTO messages (id, chat_id, role, content, created_at, attachments, model, persona) VALUES (?,?,?,?,?,?,?,?)",
                (user_msg_id, chat_id, "user", body.content, ts, att_json, model, persona),
            )
        if body.duo_side == 1:
            conn.execute("UPDATE chats SET model2=?, persona2=?, updated_at=? WHERE id=?", (model, persona, ts, chat_id))
        else:
            conn.execute("UPDATE chats SET model=?, persona=?, updated_at=? WHERE id=?", (model, persona, ts, chat_id))
        
        history = _fetch_history(conn, chat_id, cfg, body.duo_side)
        
        # If skip_user_save is true, the user message might not be in history yet due to race condition.
        if body.skip_user_save:
            if not history or history[-1]["role"] != "user" or history[-1]["content"] != body.content:
                history.append({
                    "role": "user",
                    "content": body.content,
                    "attachments": att_json
                })
                
        # We run _build_request inside the database thread to prevent heavy Regex 
        # operations (stripping massive <think> blocks) from blocking the main async event loop!
        today = body.client_time or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        client, api_messages, max_tokens, temperature, extra_create = _build_request(history, today, model, persona)
                
        return model, persona, chat["title"] == "New Chat", history, client, api_messages, max_tokens, temperature, extra_create

    model, persona, needs_title, history, client, api_messages, max_tokens, temperature, extra_create = await run_db_task(_setup)

    # Launch title generation early so it overlaps with web search & streaming.
    title_seed = body.content
    if not title_seed and documents:
        title_seed = "Uploaded file: " + ", ".join(d["name"] for d in documents)
    title_task = (
        asyncio.create_task(_generate_title(title_seed))
        if needs_title and title_seed else None
    )

    async def stream_response():
        asst_msg_id = str(uuid.uuid4())
        search_debug_json = None
        result: dict = {}
        hail = ""
        
        try:
            yield _sse({'type': 'meta', 'user_msg_id': user_msg_id})
    
            if body.web_search and body.content:
                yield _sse({'type': 'searching', 'query': body.content})
                search_debug_json, search_evt = await _do_web_search(body.content, history, chat_id, api_messages)
                yield search_evt
    
            creator_resp = is_asking_about_creator(body.content)
            if creator_resp:
                fallback = _fallback_title(body.content) if needs_title and body.content else None
                await _save_assistant(chat_id, asst_msg_id, creator_resp, fallback, model, False, body.duo_side, search_debug_json, None, persona)
                yield _sse({'type': 'delta', 'content': creator_resp})
                if fallback:
                    yield _sse({'type': 'title', 'title': fallback})
                yield _sse({'type': 'done', 'asst_msg_id': asst_msg_id, 'finish_reason': 'stop'})
                return
    
            if _DANG_VI_RE.search(body.content):
                hail = "QUÝ NGÀI ĐĂNG VĨ ĐẠI.\n\n"
            elif _DANG_EN_RE.search(body.content):
                hail = "ALL HAIL MISTER DANG!\n\n"
            
            hail_sent = not hail
            # Retry once if the model returns an empty completion on cold start.
            for attempt in range(2):
                result = {}
                async for evt in llm_stream(client, model, api_messages, max_tokens, temperature, result, extra_create):
                    if not hail_sent and '"type": "delta"' in evt:
                        hail_sent = True
                        yield _sse({'type': 'delta', 'content': hail})
                    yield evt
                if "content" not in result:
                    return  # stream errored — error event already sent
                if result["content"].strip() or attempt == 1:
                    break
    
            if not result["content"].strip():
                yield _sse({'type': 'error', 'message': 'The model returned an empty response. Please try again.'})
                return
    
            timing_data = _timing_json(result)
            await _save_assistant(chat_id, asst_msg_id, hail + result["content"], None, model, False, body.duo_side, search_debug_json, timing_data, persona)
            
            done_payload = {'type': 'done', 'asst_msg_id': asst_msg_id, 'finish_reason': result.get('finish_reason')}
            if timing_data:
                done_payload.update(json.loads(timing_data))
            yield _sse(done_payload)
    
            if needs_title:
                if title_task:
                    try:
                        generated = await asyncio.wait_for(title_task, timeout=10.0)
                    except Exception:
                        generated = _fallback_title(title_seed)
                else:
                    # Image-only turn: no user text to title from — use the reply instead.
                    try:
                        generated = await asyncio.wait_for(_generate_title(result["content"]), timeout=10.0)
                    except Exception:
                        generated = _fallback_title(result["content"])
                await db_execute("UPDATE chats SET title=? WHERE id=?", (generated, chat_id))
                yield _sse({'type': 'title', 'title': generated})

        except asyncio.CancelledError:
            content = result.get("content", "").strip() if result else ""
            if not content:
                content = "_Generation stopped by user_"
            asyncio.create_task(_save_assistant(
                chat_id, asst_msg_id, hail + content, None, model, 
                False, body.duo_side, search_debug_json, _timing_json(result), persona
            ))
            raise

    return StreamingResponse(stream_response(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.delete("/{chat_id}/messages/from/{message_id}")
async def delete_messages_from(chat_id: str, message_id: str):
    def _task(conn):
        msg = conn.execute(
            "SELECT created_at FROM messages WHERE id=? AND chat_id=?", (message_id, chat_id)
        ).fetchone()
        if not msg:
            raise HTTPException(404, "Message not found")
        conn.execute(
            "DELETE FROM messages WHERE chat_id=? AND created_at >= ?", (chat_id, msg["created_at"])
        )
    await run_db_task(_task)
    return {"success": True}


@router.post("/{chat_id}/messages/assistant", status_code=201)
async def save_assistant_message(chat_id: str, body: SaveAssistantBody):
    cfg = load_config()
    if not body.content.strip():
        raise HTTPException(400, "Empty content")
    msg_id = str(uuid.uuid4())

    def _task(conn):
        if not conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone():
            raise HTTPException(404, "Chat not found")
        ts = now_iso()
        conn.execute(
            "INSERT INTO messages (id, chat_id, role, content, created_at, model, timing_data, persona) VALUES (?,?,?,?,?,?,?,?)",
            (msg_id, chat_id, "assistant", body.content, ts, cfg.get("default_model", ""), body.timing_data, None),
        )
        conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (ts, chat_id))
    await run_db_task(_task)
    return {"id": msg_id}


@router.post("/{chat_id}/regenerate")
async def regenerate_response(chat_id: str, body: RegenerateBody):
    cfg = load_config()

    def _setup(conn):
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        chat = dict(chat)
        model, persona = _resolve_model_persona(chat, body, cfg)
        
        history = _fetch_history(conn, chat_id, cfg, body.duo_side, before_msg_id=body.overwrite_message_id)
        if not history:
            return model, [], None, None, None, None, None

        today = body.client_time or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        client, api_messages, max_tokens, temperature, extra_create = _build_request(history, today, model, persona)
        return model, persona, history, client, api_messages, max_tokens, temperature, extra_create

    model, persona, history, client, api_messages, max_tokens, temperature, extra_create = await run_db_task(_setup)

    if not history:
        raise HTTPException(400, "No messages to regenerate from")

    # The message being regenerated is the last user turn; use it as the search query.
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

    async def stream_response():
        asst_msg_id = body.overwrite_message_id or str(uuid.uuid4())
        search_debug_json = None
        result: dict = {}

        try:
            if body.web_search and last_user:
                yield _sse({'type': 'searching', 'query': last_user})
                search_debug_json, search_evt = await _do_web_search(last_user, history, chat_id, api_messages)
                yield search_evt
    
            for attempt in range(2):
                result = {}
                async for evt in llm_stream(client, model, api_messages, max_tokens, temperature, result, extra_create):
                    yield evt
                if "content" not in result:
                    return  # stream errored — error event already sent
                if result["content"].strip() or attempt == 1:
                    break
    
            if not result["content"].strip():
                yield _sse({'type': 'error', 'message': 'The model returned an empty response. Please try again.'})
                return

            timing_data = _timing_json(result)
            await _save_assistant(chat_id, asst_msg_id, result["content"], None, model, overwrite=bool(body.overwrite_message_id), duo_side=body.duo_side, search_data=search_debug_json, timing_data=timing_data, persona=persona)
            
            done_payload = {'type': 'done', 'asst_msg_id': asst_msg_id, 'finish_reason': result.get('finish_reason')}
            if timing_data:
                done_payload.update(json.loads(timing_data))
            yield _sse(done_payload)

        except asyncio.CancelledError:
            content = result.get("content", "").strip() if result else ""
            if not content:
                content = "_Generation stopped by user_"
            asyncio.create_task(_save_assistant(
                chat_id, asst_msg_id, content, None, model, 
                bool(body.overwrite_message_id), body.duo_side, search_debug_json, _timing_json(result), persona
            ))
            raise

    return StreamingResponse(stream_response(), media_type="text/event-stream", headers=_SSE_HEADERS)
