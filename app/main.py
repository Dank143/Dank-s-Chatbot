import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.config import load_config
from app.database import init_db
from app.routers.chats import router as chats_router
from app.routers.files import router as files_router
from app.routers.messages import router as messages_router
from app.routers.settings import router as settings_router, _ping_model
from app.search import shutdown as _shutdown_search
from app.search import warmup as _warmup_search

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

APP_TITLE: str = "NIM Chatbot"
STATIC_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}
PROJECT_ROOT: Path = Path(__file__).parent.parent
LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1"})
FRONTEND_PATHS: tuple[str, ...] = ("/css/", "/js/")
CONDITIONAL_HEADERS: frozenset[bytes] = frozenset(
    {b"if-modified-since", b"if-none-match"}
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm optional dependencies on startup and release search resources on shutdown."""
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


app = FastAPI(title=APP_TITLE, lifespan=lifespan)


@app.middleware("http")
async def add_no_cache_header(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Disable browser caching for mutable frontend assets during development."""
    path = request.url.path
    is_frontend = path in {"/", "/index.html"} or path.startswith(FRONTEND_PATHS)
    disable_cache = (
        request.client is not None
        and request.client.host in LOCAL_HOSTS
        and is_frontend
    )
    if disable_cache:
        request.scope["headers"] = [
            header for header in request.scope["headers"]
            if header[0] not in CONDITIONAL_HEADERS
        ]

    response = await call_next(request)
    if disable_cache:
        response.headers.update(STATIC_CACHE_HEADERS)
    return response


BOOT_ID: str = str(uuid.uuid4())


@app.get("/api/boot-id")
def boot_id() -> dict[str, str]:
    """Return the identifier for this running server process."""
    return {"id": BOOT_ID}

init_db()

app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(settings_router)
app.include_router(files_router)

icon_dir = PROJECT_ROOT / "icon"
if icon_dir.exists():
    app.mount("/icon", StaticFiles(directory=str(icon_dir)), name="icons")

static_dir = PROJECT_ROOT / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
