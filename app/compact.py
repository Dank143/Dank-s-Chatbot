import asyncio
import logging
from app.database import db_execute
from app.llm import get_client

_log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a highly efficient conversation compactor.
Given an existing summary and a batch of older messages, produce a STRUCTURED output with exactly two sections.

## Summary
A concise narrative (2-4 sentences) covering the key topics, decisions, and outcomes from the conversation so far.

## Key Facts
A bullet list of critical, discrete facts. Include: user preferences, project details, technical decisions, names, and any information that would be important to recall later. 
NEVER remove an existing Key Fact — only add new ones or update outdated ones.

Format your output exactly with those two headers.
"""

async def maybe_compact(chat_id: str, model: str, duo_side: int, max_messages: int) -> None:
    """Check if compaction is needed and spawn it if the lock is free."""
    from app.config import load_config, provider_for_model

    compact_models = load_config().get("compact_model", {})
    model = compact_models.get(provider_for_model(model)) or model

    chat = await db_execute("SELECT compacting, summary, summary2, summary_msg_id, summary_msg_id2 FROM chats WHERE id=?", (chat_id,), fetch="one")
    if not chat or chat["compacting"] == 1:
        return

    # Lock the chat for compaction
    await db_execute("UPDATE chats SET compacting=1 WHERE id=?", (chat_id,))
    
    try:
        await _run_compaction(chat_id, model, duo_side, max_messages, dict(chat))
    except Exception as e:
        _log.error("Compaction failed for chat %s: %s", chat_id, e)
    finally:
        # Unlock
        await db_execute("UPDATE chats SET compacting=0 WHERE id=?", (chat_id,))

async def _run_compaction(chat_id: str, model: str, duo_side: int, max_messages: int, chat_row: dict) -> None:
    # 1. Fetch unsummarized messages
    if duo_side == 1:
        last_msg_id = chat_row.get("summary_msg_id2")
        existing_summary = chat_row.get("summary2")
    else:
        last_msg_id = chat_row.get("summary_msg_id")
        existing_summary = chat_row.get("summary")

    query = "SELECT id, role, content FROM messages WHERE chat_id=? AND (role='user' OR duo_side=?)"
    params = [chat_id, duo_side]
    
    if last_msg_id:
        target = await db_execute("SELECT created_at FROM messages WHERE id=?", (last_msg_id,), fetch="one")
        if target:
            query += " AND created_at > ?"
            params.append(target["created_at"])
            
    query += " ORDER BY created_at ASC"
    unsummarized = await db_execute(query, tuple(params), fetch="all")
    
    count = len(unsummarized)
    if count <= max_messages:
        return # No compaction needed
        
    # We want to compact enough messages so that the active window shrinks to (max_messages // 2)
    # The number of messages to keep is target_keep = max(1, max_messages // 2)
    target_keep = max(1, max_messages // 2)
    to_compact_count = count - target_keep
    
    if to_compact_count <= 0:
        return
        
    batch = unsummarized[:to_compact_count]
    new_last_msg_id = batch[-1]["id"]
    
    # 2. Build the LLM payload
    # Format the messages for the LLM
    formatted_batch = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in batch)
    
    user_prompt = "Existing Summary/Key Facts:\n"
    user_prompt += (existing_summary or "(None)") + "\n\n"
    user_prompt += "New Messages to Compact:\n"
    user_prompt += formatted_batch
    
    # 3. Call the LLM
    from app.config import provider_for_model
    prov = provider_for_model(model)
    client = get_client(prov)
    
    _log.info("Starting background compaction for chat %s (compacting %d messages)", chat_id, to_compact_count)
    
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3, # Low temp for factual consistency
        max_tokens=2048,
    )
    
    new_summary = resp.choices[0].message.content.strip()
    
    # 4. Save to database
    if duo_side == 1:
        await db_execute("UPDATE chats SET summary2=?, summary_msg_id2=? WHERE id=?", (new_summary, new_last_msg_id, chat_id))
    else:
        await db_execute("UPDATE chats SET summary=?, summary_msg_id=? WHERE id=?", (new_summary, new_last_msg_id, chat_id))
        
    _log.info("Compaction finished for chat %s", chat_id)
