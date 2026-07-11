import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure our loggers reach the console (uvicorn only configures its own).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers.chats import router as chats_router
from app.routers.files import router as files_router
from app.routers.messages import router as messages_router
from app.routers.settings import router as settings_router, _ping_model
from app.search import warmup as _warmup_search, shutdown as _shutdown_search
from app.config import load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    nim_title = cfg.get("title_model_nim")
    ollama_title = cfg.get("title_model_ollama")
    
    # Warm aux LLMs and DDG session concurrently at startup.
    if nim_title:
        asyncio.create_task(_ping_model(nim_title, "nim"))
    if ollama_title:
        asyncio.create_task(_ping_model(ollama_title, "ollama"))
        
    asyncio.create_task(_warmup_search())
    yield
    await _shutdown_search()


app = FastAPI(title="NIM Chatbot", lifespan=lifespan)

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

_BOOT_ID = str(uuid.uuid4())

@app.get("/api/boot-id")
def boot_id():
    return {"id": _BOOT_ID}

init_db()

app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(settings_router)
app.include_router(files_router)

icon_dir = Path(__file__).parent.parent / "icon"
if icon_dir.exists():
    app.mount("/icon", StaticFiles(directory=str(icon_dir)), name="icons")

static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
