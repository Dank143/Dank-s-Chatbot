import uuid

from fastapi import APIRouter, HTTPException

from app.config import load_config
from app.database import db_execute, now_iso, run_db_task
from app.schemas import CreateChatBody, UpdateChatBody

router = APIRouter(prefix="/api/chats")


@router.get("")
async def list_chats():
    return await db_execute(
        "SELECT id, title, model, model2, starred, created_at, updated_at, duo_mode, persona, persona2 "
        "FROM chats ORDER BY starred DESC, updated_at DESC", fetch="all"
    )


@router.post("", status_code=201)
async def create_chat(body: CreateChatBody):
    cfg = load_config()
    chat_id = str(uuid.uuid4())
    ts = now_iso()
    model = body.model or cfg.get("default_model")
    model2 = body.model2
    duo_mode = 1 if body.duo_mode else 0
    persona = body.persona or "default"
    persona2 = body.persona2

    await db_execute(
        "INSERT INTO chats (id, title, model, model2, created_at, updated_at, duo_mode, persona, persona2) VALUES (?,?,?,?,?,?,?,?,?)",
        (chat_id, body.title, model, model2, ts, ts, duo_mode, persona, persona2)
    )
    return {"id": chat_id, "title": body.title, "model": model, "model2": model2,
            "starred": 0, "created_at": ts, "updated_at": ts, "duo_mode": duo_mode, "persona": persona, "persona2": persona2}


@router.get("/{chat_id}")
async def get_chat(chat_id: str):
    def _task(conn):
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        msgs = conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)).fetchall()
        return {**dict(chat), "messages": [dict(m) for m in msgs]}
    return await run_db_task(_task)


@router.get("/{chat_id}/compacting")
async def get_chat_compacting_status(chat_id: str):
    def _task(conn):
        chat = conn.execute("SELECT compacting FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        return {"compacting": chat["compacting"]}
    return await run_db_task(_task)


@router.patch("/{chat_id}")
async def update_chat(chat_id: str, body: UpdateChatBody):
    def _task(conn):
        if not conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone():
            raise HTTPException(404, "Chat not found")
        ts = now_iso()
        sets: list[str] = ["updated_at=?"]
        params: list[str | int] = [ts]
        if body.title is not None:
            sets.append("title=?"); params.append(body.title)
        if body.model is not None:
            sets.append("model=?"); params.append(body.model)
        if body.model2 is not None:
            sets.append("model2=?"); params.append(body.model2)
        if body.starred is not None:
            sets.append("starred=?"); params.append(int(body.starred))
        if body.duo_mode is not None:
            sets.append("duo_mode=?"); params.append(1 if body.duo_mode else 0)
        if body.persona is not None:
            sets.append("persona=?"); params.append(body.persona)
        if body.persona2 is not None:
            sets.append("persona2=?"); params.append(body.persona2)
        params.append(chat_id)
        conn.execute(f"UPDATE chats SET {', '.join(sets)} WHERE id=?", params)
    await run_db_task(_task)
    return {"success": True}


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str):
    await db_execute("DELETE FROM chats WHERE id=?", (chat_id,))
    return {"success": True}


@router.post("/{chat_id}/duplicate")
async def duplicate_chat(chat_id: str):
    import re

    def _task(conn):
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        
        base_title = chat["title"]
        match = re.search(r' \((\d+)\)$', base_title)
        if match:
            n = int(match.group(1))
            new_title = base_title[:match.start()] + f" ({n+1})"
        else:
            new_title = base_title + " (1)"
            
        new_chat_id = str(uuid.uuid4())
        ts = now_iso()
        
        conn.execute(
            """INSERT INTO chats (
                id, title, model, model2, starred, created_at, updated_at, 
                duo_mode, persona, persona2, summary, summary2, summary_msg_id, summary_msg_id2, compacting
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_chat_id, new_title, chat["model"], chat["model2"], chat["starred"], 
                ts, ts, chat["duo_mode"], chat["persona"], chat["persona2"], 
                chat["summary"], chat["summary2"], chat["summary_msg_id"], chat["summary_msg_id2"], 0
            )
        )
        
        msgs = conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at", (chat_id,)).fetchall()
        for msg in msgs:
            msg_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO messages (
                    id, chat_id, role, content, created_at, attachments, model, 
                    duo_side, search_data, timing_data, persona
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    msg_id, new_chat_id, msg["role"], msg["content"], msg["created_at"], 
                    msg["attachments"], msg["model"], msg["duo_side"], 
                    msg["search_data"], msg["timing_data"], msg["persona"]
                )
            )
        return {"id": new_chat_id}

    return await run_db_task(_task)
