import asyncio
import logging
import time

from fastembed import TextEmbedding
from config import load_config
from .cache import get_cached_config

_log = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"
_model: TextEmbedding | None = None
_load_lock = asyncio.Lock()
_semaphore = asyncio.Semaphore(4)  # Cap concurrent CPU-bound inference

_LOAD_RETRY_COOLDOWN_S = 30.0  # Back off after failed load attempts
_last_load_attempt: float = 0.0


async def warmup_embedder() -> None:
    """Load the ONNX model once at boot (requires restart to change model)."""
    global _model, _last_load_attempt
    if _model is not None:
        return
    async with _load_lock:
        if _model is not None:
            return
        _last_load_attempt = time.monotonic()
        try:
            cfg = await get_cached_config(load_config)
            name = cfg.get("embed_model_fastembed", _DEFAULT_MODEL)
            _model = await asyncio.to_thread(TextEmbedding, name)
            _log.info("fastembed model %r loaded", name)
        except Exception:
            _log.warning("fastembed model load failed", exc_info=True)


async def _ensure_loaded() -> bool:
    """Lazy-load with cooldown on failures."""
    if _model is not None:
        return True
    if _last_load_attempt and (time.monotonic() - _last_load_attempt) < _LOAD_RETRY_COOLDOWN_S:
        return False
    await warmup_embedder()
    return _model is not None


async def embed_texts(texts: list[str]) -> "list[list[float]] | None":
    """Embed a batch locally. Returns None on failure (caller falls back to heuristic sort)."""
    if not texts:
        return []
    if not await _ensure_loaded():
        return None
    try:
        async with _semaphore:
            vecs = await asyncio.to_thread(lambda: list(_model.embed(texts)))
        return [v.tolist() for v in vecs]
    except Exception:
        _log.warning("fastembed embed failed", exc_info=True)
        return None
