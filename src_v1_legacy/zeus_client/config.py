"""config.json load/save."""
import asyncio
import json
import os

from zeus_client.constants import (
    CONFIG_PATH,
    EXAMPLE_CONFIG_PATH,
    USER_CONFIG_DIR,
    bundled_example_config_path,
)

_ZEUS_LEGACY_CONNECTION_KEYS = frozenset({"id", "name", "workbench_url"})
_LLM_PROVIDER_FIELDS = frozenset({"label", "base_url", "api_key", "models"})


def _clean_zeus_entry(entry: dict) -> dict:
    if not isinstance(entry, dict):
        return {}
    return {k: v for k, v in entry.items() if k not in _ZEUS_LEGACY_CONNECTION_KEYS}


def _clean_llm_provider_entry(entry: dict) -> dict:
    if not isinstance(entry, dict):
        return {}
    return {k: v for k, v in entry.items() if k in _LLM_PROVIDER_FIELDS}


def _normalize_zeus_config(cfg: dict) -> None:
    zeus = cfg.get("zeus")
    connections = cfg.pop("zeus_connections", None)
    default_name = (cfg.pop("default_zeus_connection", None) or "").strip()

    if connections and isinstance(connections, list) and connections:
        entry = None
        if default_name:
            entry = next((c for c in connections if c.get("name") == default_name), None)
        if entry is None:
            entry = connections[0]
        zeus = _clean_zeus_entry(entry)
    elif isinstance(zeus, dict):
        zeus = _clean_zeus_entry(zeus)

    if isinstance(zeus, dict) and zeus:
        cfg["zeus"] = zeus
    else:
        cfg.pop("zeus", None)


def _normalize_llm_provider_config(cfg: dict) -> None:
    llm_provider = cfg.get("llm_provider")
    providers = cfg.pop("providers", None)
    default_provider = (cfg.pop("default_provider", None) or "").strip()
    cfg.pop("provider_pool", None)

    if providers and isinstance(providers, dict) and providers:
        entry = providers.get(default_provider) if default_provider else None
        if entry is None:
            entry = next(iter(providers.values()))
        llm_provider = _clean_llm_provider_entry(entry)
    elif isinstance(llm_provider, dict):
        llm_provider = _clean_llm_provider_entry(llm_provider)

    if isinstance(llm_provider, dict) and llm_provider:
        cfg["llm_provider"] = llm_provider
    else:
        cfg.pop("llm_provider", None)


def normalize_config(cfg: dict) -> dict:
    """Normalize legacy config shapes to single ``zeus`` and ``llm_provider`` objects."""
    _normalize_zeus_config(cfg)
    _normalize_llm_provider_config(cfg)
    return cfg


def resolve_zeus_config(cfg: dict) -> dict:
    """Return the Zeus connection settings for API handlers."""
    zeus = cfg.get("zeus")
    if not isinstance(zeus, dict) or not zeus:
        return {}

    resolved = dict(zeus)

    # Runtime override for Docker — never persist back to config.json.
    zeus_url_env = (os.environ.get("ZEUS_URL") or "").strip()
    if zeus_url_env:
        resolved["url"] = zeus_url_env

    return resolved


def resolve_llm_provider_config(cfg: dict) -> dict:
    """Return the LLM provider settings for API handlers."""
    llm_provider = cfg.get("llm_provider")
    if not isinstance(llm_provider, dict) or not llm_provider:
        return {}
    return dict(llm_provider)


def _load_config_sync():
    """Read config.json, auto-creating it from config.example.json on
    first run. ZEUS_URL is applied at resolve time (see resolve_zeus_config).

    This touches the disk, so route handlers call it through
    `asyncio.to_thread` to keep the event loop unblocked."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            CONFIG_PATH.write_text(EXAMPLE_CONFIG_PATH.read_text())
        elif bundled_example_config_path().exists():
            CONFIG_PATH.write_text(bundled_example_config_path().read_text())
    with open(CONFIG_PATH) as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"config.json is not valid JSON at line {e.lineno} column {e.colno} (char {e.pos}). "
                f"Common cause: // style comments (JSON does not allow comments). "
                f"Use a top-level or sibling '_comment' string key instead. "
                f"Original error: {e.msg}"
            ) from e
    return normalize_config(cfg)


def _save_config_sync(cfg):
    cfg.pop("_comment", None)
    normalize_config(cfg)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


async def load_config():
    return await asyncio.to_thread(_load_config_sync)


async def save_config(cfg):
    await asyncio.to_thread(_save_config_sync, cfg)