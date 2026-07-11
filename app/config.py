import os
import re
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(__file__).parent.parent / "models.yaml"
ENV_PATH = Path(__file__).parent.parent / ".env"
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / ".system_prompt"

_config_cache: dict = {}
_config_mtime: float = 0.0
_config_checked: float = 0.0
_yaml_nim_key: str = ""   # YAML fallback key
_yaml_ollama_key: str = ""
_yaml_cloudflare_key: str = ""
_yaml_cloudflare_account_id: str = ""
_STAT_TTL = 5.0  # seconds between stat() calls

_PROVIDERS = ("nim", "ollama", "cloudflare")
_ENV_KEY_MAP = {"nim": "NVIDIA_API_KEY", "ollama": "OLLAMA_API_KEY", "cloudflare": "CLOUDFLARE_API_KEY"}


def load_config() -> dict:
    """Return cached models.yaml, re-reading only when the file's mtime changes."""
    global _config_cache, _config_mtime, _config_checked, _yaml_nim_key, _yaml_ollama_key, _yaml_cloudflare_key, _yaml_cloudflare_account_id
    now = time.monotonic()
    if now - _config_checked >= _STAT_TTL:
        _config_checked = now
        mtime = CONFIG_PATH.stat().st_mtime
        if mtime != _config_mtime:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _config_cache = yaml.safe_load(f)
            _config_mtime = mtime
            _yaml_nim_key = _config_cache.get("api_nim", {}).get("key", "")
            _yaml_ollama_key = _config_cache.get("api_ollama", {}).get("key", "")
            _yaml_cloudflare_key = _config_cache.get("api_cloudflare", {}).get("key", "")
            _yaml_cloudflare_account_id = _config_cache.get("api_cloudflare", {}).get("account_id", "")
    # Env keys override YAML keys; fall back to YAML if env is unset.
    env_nim = os.environ.get("NVIDIA_API_KEY", "")
    _config_cache.setdefault("api_nim", {})["key"] = env_nim or _yaml_nim_key
    env_ollama = os.environ.get("OLLAMA_API_KEY", "")
    _config_cache.setdefault("api_ollama", {})["key"] = env_ollama or _yaml_ollama_key
    env_cloudflare = os.environ.get("CLOUDFLARE_API_KEY", "")
    _config_cache.setdefault("api_cloudflare", {})["key"] = env_cloudflare or _yaml_cloudflare_key
    env_cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    _config_cache.setdefault("api_cloudflare", {})["account_id"] = env_cf_account or _yaml_cloudflare_account_id
    if SYSTEM_PROMPT_PATH.exists():
        _config_cache.setdefault("defaults", {})["system_prompt"] = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return _config_cache


def provider_api(provider: str) -> dict:
    """Return {key, base_url} for the given provider ('nim' or 'ollama')."""
    cfg = load_config()
    section = cfg.get(f"api_{provider}", {})
    key = section.get("key", "")
    base_url = section.get("base_url", "")
    account_id = section.get("account_id", "")
    
    if provider == "nim":
        env_url = os.environ.get("NVIDIA_BASE_URL")
        if env_url:
            base_url = env_url
    elif provider == "ollama":
        env_url = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST")
        if env_url:
            base_url = env_url
            if not base_url.endswith("/v1") and not base_url.endswith("/v1/"):
                base_url = base_url.rstrip("/") + "/v1"
    elif provider == "cloudflare":
        env_url = os.environ.get("CLOUDFLARE_BASE_URL")
        env_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        if env_account:
            account_id = env_account
        if env_url:
            base_url = env_url
        elif account_id:
            base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
                
    return {"key": key, "base_url": base_url, "account_id": account_id}


def provider_models(provider: str) -> list:
    """Return the model list for the given provider."""
    cfg = load_config()
    return cfg.get(f"models_{provider}", [])


def provider_default_model(provider: str) -> str:
    """Return the default model ID for the given provider."""
    cfg = load_config()
    models = provider_models(provider)
    return cfg.get(f"default_model_{provider}") or (models[0]["id"] if models else "")


def provider_for_model(model_id: str) -> str:
    """Determine which provider a model belongs to. Falls back to 'nim'."""
    cfg = load_config()
    for p in _PROVIDERS:
        for m in cfg.get(f"models_{p}", []):
            if m.get("id") == model_id:
                return p
    return "nim"


def provider_model_info(model_id: str) -> dict | None:
    """Return the model entry from models.yaml for the given model id."""
    cfg = load_config()
    for p in _PROVIDERS:
        for m in cfg.get(f"models_{p}", []):
            if m.get("id") == model_id:
                return m
    return None


def set_env_var(env_var: str, value: str) -> None:
    """Write a specific environment variable to .env and update os.environ in-process."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    lines = [l for l in lines if not l.startswith(f"{env_var}=")]
    if value:
        lines.append(f"{env_var}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if value:
        os.environ[env_var] = value
    else:
        os.environ.pop(env_var, None)


def set_env_key(provider: str, key: str) -> None:
    """Write the API key for *provider* to .env and update os.environ in-process."""
    env_var = _ENV_KEY_MAP.get(provider, "NVIDIA_API_KEY")
    set_env_var(env_var, key)


def replace_scalar(content: str, section: str, key: str, value: str) -> str:
    """Replace a `key: value` scalar inside a specific top-level section in raw YAML, preserving layout."""
    pattern = rf'(^{section}:\s*\n(?:\s+.*\n)*?^\s+{re.escape(key)}\s*:\s*).*$'
    return re.sub(
        pattern,
        lambda m: m.group(1) + value,
        content,
        flags=re.MULTILINE,
    )
