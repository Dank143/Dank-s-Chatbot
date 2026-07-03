import asyncio
import logging
import time

from fastembed import TextEmbedding
from config import load_config

_log = logging.getLogger(__name__)

_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_model: TextEmbedding | None = None
_load_lock = asyncio.Lock()
# CPU-bound work — cap concurrent inference so simultaneous chat requests
# don't fight each other for cores the way unlimited to_thread calls would.
_semaphore = asyncio.Semaphore(4)

# If a load attempt fails (bad model path, disk/network issue), back off for
# this long before trying again instead of re-attempting the full load on
# every request that lands in the meantime — a broken load is CPU/disk-heavy
# and unlikely to fix itself within milliseconds.
_LOAD_RETRY_COOLDOWN_S = 30.0
_last_load_attempt: float = 0.0


async def warmup_embedder() -> None:
    """Load the ONNX model once at boot. Changing the model name requires a
    process restart — this is intentionally NOT hot-reloaded like other
    models.yaml values, since swapping models means re-downloading/loading."""
    global _model, _last_load_attempt
    if _model is not None:
        return
    async with _load_lock:
        if _model is not None:
            return
        _last_load_attempt = time.monotonic()
        try:
            cfg = load_config()
            name = cfg.get("embed_model_fastembed", _DEFAULT_MODEL)
            _model = await asyncio.to_thread(TextEmbedding, name)
            _log.info("fastembed model %r loaded", name)
        except Exception:
            _log.warning("fastembed model load failed", exc_info=True)


async def _ensure_loaded() -> bool:
    """Defensive lazy-load, in case a request lands before warmup() finishes.
    After a failed load, skip retrying until the cooldown elapses so a
    persistently broken model path doesn't get re-attempted on every request."""
    if _model is not None:
        return True
    if _last_load_attempt and (time.monotonic() - _last_load_attempt) < _LOAD_RETRY_COOLDOWN_S:
        return False
    await warmup_embedder()
    return _model is not None


async def embed_texts(texts: list[str]) -> "list[list[float]] | None":
    """Embed a batch locally. Returns None on failure — caller (`_rerank`)
    already treats None as 'skip reranking, fall back to heuristic sort'."""
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