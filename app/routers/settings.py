import re
import time
import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Body, Query
from openai import AsyncOpenAI

from app.config import (
    CONFIG_PATH, load_config, replace_scalar, set_env_key, set_env_var,
    provider_api, provider_models, provider_default_model, provider_for_model,
    get_personas, get_common_system_prompt
)
from app.llm import get_client
from app.schemas import UpdateSettingsBody, VerifyKeyBody, WarmupBody

router = APIRouter(prefix="/api")

# Per-model warmup timestamps. TTL below client keep-alive (4 min) so periodic
# pings actually re-warm instead of being throttled.
_last_warmup: dict[str, float] = {}
_WARMUP_TTL = 230
_PERSONA_ORDER = {
    "default": 0, "unhinged": 1, "furious": 2, "horny": 3,
    "caveman": 4, "weeboo": 5, "drunk": 6, "batman": 7,
    "shakespeare": 8, "god": 9, "emo": 10, "sassy": 11,
    "british": 12, "french": 13, "american": 14, "asian": 15,
}


async def _ping_model(model: str, provider: str = "nim") -> None:
    """One-token request to spin up a serverless model; errors silently ignored."""
    api = provider_api(provider)
    if not api.get("key") or not model:
        return
    try:
        client = get_client(provider)
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            stream=False,
        )
    except Exception:
        pass


@router.post("/warmup")
async def warmup(background_tasks: BackgroundTasks, body: WarmupBody | None = Body(default=None)):
    """Background-warm a model (default if unspecified), throttled per model."""
    model = (body.model if body else None)
    if not model:
        # Fall back to NIM default when no model specified (boot warmup).
        model = provider_default_model("nim")
    if not model:
        return {"ok": True}
    now = time.monotonic()
    if now - _last_warmup.get(model, 0.0) > _WARMUP_TTL:
        _last_warmup[model] = now
        prov = provider_for_model(model)
        background_tasks.add_task(_ping_model, model, prov)
    return {"ok": True}


@router.get("/models")
def get_models(provider: str = Query("nim")):
    return {
        "models": provider_models(provider),
        "default": provider_default_model(provider),
    }


@router.get("/settings")
def get_settings(provider: str = Query("nim"), reveal_key: bool = False):
    api = provider_api(provider)
    key = api.get("key", "")
    placeholder_nim = "nvapi-YOUR_KEY_HERE"
    has_key = bool(key and key != placeholder_nim)
    hint = key[-4:] if has_key else ""
    temperature = load_config().get("defaults", {}).get("temperature", 0.7)
    return {
        "base_url": api.get("base_url", ""),
        "account_id": api.get("account_id", ""),
        "has_key": has_key,
        "key_hint": hint,
        "key_len": len(key) if has_key else 0,
        "key": key if has_key and reveal_key else "",
        "temperature": temperature,
    }


@router.post("/verify-key")
async def verify_key(body: VerifyKeyBody):
    """Validate a key/base_url by making a 1-token call; maps errors to a reason."""
    key = body.key.strip()
    logger.info(
        "VERIFY KEY: provider=%s, base_url=%s, key_len=%d, key_hint=%s",
        body.provider, body.base_url.strip(), len(key),
        key[-4:] if len(key) >= 4 else key,
    )
    if body.provider == "nim" and not re.match(r"^nvapi-[A-Za-z0-9_\-]{20,}$", key):
        return {"valid": False, "error": "Not a valid NVIDIA NIM key (must start with nvapi-)."}
    if not key:
        return {"valid": False, "error": "API key cannot be empty."}
    try:
        # Use a small generic model for verification.
        if body.provider == "nim":
            verify_model = "meta/llama-3.1-8b-instruct"
        elif body.provider == "cloudflare":
            verify_model = "@cf/meta/llama-3.1-8b-instruct-fp8"
        else:
            verify_model = "minimax-m3:cloud"
        
        base_url_str = body.base_url.strip()
        if body.provider == "cloudflare" and body.account_id:
            if "{account_id}" in base_url_str:
                base_url_str = base_url_str.replace("{account_id}", body.account_id.strip())
            else:
                base_url_str = re.sub(r"accounts/[^/]+", f"accounts/{body.account_id.strip()}", base_url_str)
            
        client = AsyncOpenAI(api_key=key, base_url=base_url_str, timeout=5.0)
        await client.chat.completions.create(
            model=verify_model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        is_local = "localhost" in body.base_url.lower() or "127.0.0.1" in body.base_url
        msg = "Local endpoint connected." if is_local else "Key is valid!"
        return {"valid": True, "message": msg}
    except Exception as exc:
        msg = str(exc)
        normalized_message = msg.lower()
        if "401" in msg or "403" in msg or "unauthorized" in normalized_message or "invalid" in normalized_message or "forbidden" in normalized_message:
            return {"valid": False, "error": "Invalid API key."}
        if "404" in msg or "connect" in normalized_message or "timeout" in normalized_message:
            return {"valid": False, "error": "Could not reach the API endpoint. Check Base URL."}
        return {"valid": False, "error": msg[:120]}


@router.patch("/settings")
def update_settings(body: UpdateSettingsBody):
    """Write key/base_url/temperature back into config.yaml in place."""
    prov = body.provider or "nim"
    if body.key is not None:
        set_env_key(prov, body.key.strip())
    text = CONFIG_PATH.read_text(encoding="utf-8")
    if body.base_url is not None:
        text = replace_scalar(text, f"api_{prov}", "base_url", body.base_url.strip())
    if body.account_id is not None:
        text = replace_scalar(text, f"api_{prov}", "account_id", body.account_id.strip())
        if prov == "cloudflare":
            set_env_var("CLOUDFLARE_ACCOUNT_ID", body.account_id.strip())
    if body.temperature is not None:
        text = replace_scalar(text, "defaults", "temperature", str(round(body.temperature, 2)))
    CONFIG_PATH.write_text(text, encoding="utf-8")
    return {"success": True}


@router.get("/personas")
async def list_personas():
    """
    Returns a list of available persona names based on files in the personas directory.
    """
    personas = get_personas()
    
    persona_list = [
        {"id": name, "description": content}
        for name, content in personas.items()
    ]
        
    # Ensure default is always present
    if not any(persona["id"] == "default" for persona in persona_list):
        persona_list.append({"id": "default", "description": "The original and vanilla AI assistant."})
        
    persona_list.sort(key=lambda persona: _PERSONA_ORDER.get(persona["id"].lower(), 99))
        
    return {"personas": persona_list, "default": "default"}
