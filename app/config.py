import os
import re
import time
from pathlib import Path
from typing import Any, TypedDict, cast

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT: Path = Path(__file__).parent.parent
CONFIG_PATH: Path = PROJECT_ROOT / "config.yaml"
ENV_PATH: Path = PROJECT_ROOT / ".env"
SYSTEM_PROMPT_PATH: Path = PROJECT_ROOT / ".system_prompt"
PERSONAS_DIR: Path = PROJECT_ROOT / "personas"
CONFIG_STAT_TTL_SECONDS: float = 5.0


class ProviderApiConfig(TypedDict):
    """Resolved connection settings for an OpenAI-compatible provider."""

    key: str
    base_url: str
    account_id: str


class ModelConfig(TypedDict, total=False):
    """The model metadata consumed by provider selection and the UI."""

    id: str
    name: str
    icon: str
    description: str
    reasoning: str
    stats: dict[str, int]


ConfigData = dict[str, Any]

_config_cache: ConfigData = {}
_config_mtime: float = 0.0
_config_checked: float = 0.0
_yaml_nim_key: str = ""   # YAML fallback key
_yaml_ollama_key: str = ""
_yaml_cloudflare_key: str = ""
_yaml_cloudflare_account_id: str = ""
# model_id -> (provider, model_entry) for O(1) lookups
_model_index: dict[str, tuple[str, ModelConfig]] = {}

PROVIDERS: tuple[str, ...] = ("nim", "ollama", "cloudflare")
ENV_KEY_BY_PROVIDER: dict[str, str] = {
    "nim": "NVIDIA_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "cloudflare": "CLOUDFLARE_API_KEY",
}


def load_config() -> ConfigData:
    """Return cached config.yaml, re-reading only when the file's mtime changes."""
    global _config_cache, _config_mtime, _config_checked, _yaml_nim_key, _yaml_ollama_key, _yaml_cloudflare_key, _yaml_cloudflare_account_id, _model_index
    now = time.monotonic()
    if now - _config_checked >= CONFIG_STAT_TTL_SECONDS:
        _config_checked = now
        mtime = CONFIG_PATH.stat().st_mtime
        if mtime != _config_mtime:
            with CONFIG_PATH.open(encoding="utf-8") as config_file:
                loaded_config = yaml.safe_load(config_file)
            if not isinstance(loaded_config, dict):
                raise ValueError("config.yaml must contain a top-level mapping.")
            _config_cache = loaded_config
            _config_mtime = mtime
            _yaml_nim_key = _config_cache.get("api_nim", {}).get("key", "")
            _yaml_ollama_key = _config_cache.get("api_ollama", {}).get("key", "")
            _yaml_cloudflare_key = _config_cache.get("api_cloudflare", {}).get("key", "")
            _yaml_cloudflare_account_id = _config_cache.get("api_cloudflare", {}).get("account_id", "")
            # Rebuild the model index on config reload.
            idx: dict[str, tuple[str, ModelConfig]] = {}
            for provider in PROVIDERS:
                configured_models = _config_cache.get(f"models_{provider}", [])
                for model in configured_models if isinstance(configured_models, list) else []:
                    if not isinstance(model, dict):
                        continue
                    model_entry: ModelConfig = model
                    mid = model_entry.get("id")
                    if mid:
                        idx[mid] = (provider, model_entry)
            _model_index = idx
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


def provider_api(provider: str) -> ProviderApiConfig:
    """Return resolved credentials and endpoint settings for a provider."""
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


def provider_models(provider: str) -> list[ModelConfig]:
    """Return the model list for the given provider."""
    cfg = load_config()
    models = cfg.get(f"models_{provider}", [])
    return cast(list[ModelConfig], models) if isinstance(models, list) else []


def provider_default_model(provider: str) -> str:
    """Return the default model ID for the given provider."""
    cfg = load_config()
    models = provider_models(provider)
    return cfg.get(f"default_model_{provider}") or (models[0]["id"] if models else "")


def provider_for_model(model_id: str) -> str:
    """Determine which provider a model belongs to. Falls back to 'nim'."""
    load_config()  # ensure index is fresh
    entry = _model_index.get(model_id)
    return entry[0] if entry else "nim"


def provider_model_info(model_id: str) -> ModelConfig | None:
    """Return the model entry from config.yaml for the given model id."""
    load_config()  # ensure index is fresh
    entry = _model_index.get(model_id)
    return entry[1] if entry else None


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
    env_var = ENV_KEY_BY_PROVIDER.get(provider, "NVIDIA_API_KEY")
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


_sys_prompt_cache: str = ""
_sys_prompt_mtime: float = 0.0
_sys_prompt_checked: float = 0.0


def get_common_system_prompt() -> str:
    """Return the base system prompt from the root directory (stat-cached)."""
    global _sys_prompt_cache, _sys_prompt_mtime, _sys_prompt_checked
    path = SYSTEM_PROMPT_PATH
    now = time.monotonic()
    if now - _sys_prompt_checked >= CONFIG_STAT_TTL_SECONDS:
        _sys_prompt_checked = now
        try:
            if path.is_file():
                mtime = path.stat().st_mtime
                if mtime != _sys_prompt_mtime:
                    _sys_prompt_mtime = mtime
                    _sys_prompt_cache = path.read_text(encoding="utf-8").strip()
            else:
                _sys_prompt_cache = ""
        except Exception:
            pass
    return _sys_prompt_cache


_personas_cache: dict[str, str] = {}
_personas_mtime: float = 0.0
_personas_checked: float = 0.0
def get_personas() -> dict[str, str]:
    """Scan the personas directory for .txt files and return a dict of persona -> prompt (stat-cached)."""
    global _personas_cache, _personas_mtime, _personas_checked
    now = time.monotonic()
    if now - _personas_checked >= CONFIG_STAT_TTL_SECONDS:
        _personas_checked = now
        try:
            if PERSONAS_DIR.is_dir():
                # Use the directory's own mtime as the change signal.
                mtime = PERSONAS_DIR.stat().st_mtime
                if mtime != _personas_mtime:
                    _personas_mtime = mtime
                    personas: dict[str, str] = {}
                    for path in PERSONAS_DIR.glob("*.txt"):
                        if not path.is_file():
                            continue
                        try:
                            personas[path.stem] = path.read_text(encoding="utf-8").strip()
                        except Exception:
                            pass
                    _personas_cache = personas
        except Exception:
            pass
    return _personas_cache
