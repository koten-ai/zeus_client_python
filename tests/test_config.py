"""Config load/save and Zeus connection resolution tests."""
import json

import pytest

from zeus_client.config import (
    _load_config_sync,
    _save_config_sync,
    load_config,
    normalize_config,
    resolve_llm_provider_config,
    resolve_zeus_config,
    save_config,
)


def test_resolve_zeus_config_returns_zeus_section():
    cfg = {
        "zeus": {
            "url": "http://zeus:8080",
            "auth_mode": "basic",
        },
    }
    z = resolve_zeus_config(cfg)
    assert z["url"] == "http://zeus:8080"
    assert z["auth_mode"] == "basic"


def test_zeus_connections_migrates_to_single_zeus():
    cfg = normalize_config({
        "default_zeus_connection": "staging",
        "zeus_connections": [
            {"name": "default", "url": "http://default:8080", "auth_mode": "none"},
            {"name": "staging", "url": "http://staging:8080", "auth_mode": "basic"},
        ],
    })
    assert "zeus_connections" not in cfg
    assert "default_zeus_connection" not in cfg
    assert cfg["zeus"]["url"] == "http://staging:8080"
    assert cfg["zeus"]["auth_mode"] == "basic"


def test_zeus_connections_falls_back_to_first_when_default_missing():
    cfg = normalize_config({
        "default_zeus_connection": "nonexistent",
        "zeus_connections": [
            {"name": "default", "url": "http://default:8080", "auth_mode": "none"},
            {"name": "staging", "url": "http://staging:8080", "auth_mode": "basic"},
        ],
    })
    assert cfg["zeus"]["url"] == "http://default:8080"


def test_zeus_url_env_overrides_at_resolve_only(monkeypatch):
    cfg = normalize_config({
        "zeus": {"url": "http://default:8080", "auth_mode": "none"},
    })
    monkeypatch.setenv("ZEUS_URL", "http://docker-zeus:8080")
    assert cfg["zeus"]["url"] == "http://default:8080"
    z = resolve_zeus_config(cfg)
    assert z["url"] == "http://docker-zeus:8080"


def test_resolve_empty_when_no_zeus():
    assert resolve_zeus_config({}) == {}


def test_strips_legacy_connection_fields():
    cfg = normalize_config({
        "zeus": {
            "id": "zeus_default",
            "name": "default",
            "workbench_url": "http://workbench:3000",
            "url": "http://zeus:8080",
            "auth_mode": "none",
        },
    })
    assert "id" not in cfg["zeus"]
    assert "name" not in cfg["zeus"]
    assert "workbench_url" not in cfg["zeus"]
    assert cfg["zeus"]["url"] == "http://zeus:8080"


def test_resolve_llm_provider_config_returns_section():
    cfg = {
        "llm_provider": {
            "label": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "models": ["gpt-4o"],
        },
    }
    provider = resolve_llm_provider_config(cfg)
    assert provider["base_url"] == "https://api.openai.com/v1"
    assert provider["models"] == ["gpt-4o"]


def test_providers_migrates_to_single_llm_provider():
    cfg = normalize_config({
        "default_provider": "openai",
        "provider_pool": ["grok", "openai"],
        "providers": {
            "grok": {
                "label": "xAI Grok",
                "base_url": "https://api.x.ai/v1",
                "api_key": "",
                "models": ["grok-4"],
            },
            "openai": {
                "label": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "models": ["gpt-4o"],
            },
        },
    })
    assert "providers" not in cfg
    assert "default_provider" not in cfg
    assert "provider_pool" not in cfg
    assert cfg["llm_provider"]["base_url"] == "https://api.openai.com/v1"
    assert cfg["llm_provider"]["models"] == ["gpt-4o"]


def test_providers_falls_back_to_first_when_default_missing():
    cfg = normalize_config({
        "default_provider": "missing",
        "providers": {
            "grok": {
                "label": "xAI Grok",
                "base_url": "https://api.x.ai/v1",
                "api_key": "",
                "models": ["grok-4"],
            },
            "openai": {
                "label": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "models": ["gpt-4o"],
            },
        },
    })
    assert cfg["llm_provider"]["base_url"] == "https://api.x.ai/v1"


def test_strips_extra_llm_provider_fields():
    cfg = normalize_config({
        "llm_provider": {
            "label": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "models": ["gpt-4o"],
            "extra": "ignored",
        },
    })
    assert "extra" not in cfg["llm_provider"]


@pytest.mark.asyncio
async def test_load_and_save_config(patch_paths, sample_config):
    loaded = await load_config()
    assert loaded["llm_provider"]["models"] == ["grok-4"]
    sample_config["llm_provider"]["models"] = ["gpt-4o"]
    await save_config(sample_config)
    again = await load_config()
    assert again["llm_provider"]["models"] == ["gpt-4o"]


def test_load_config_creates_from_example(patch_paths, repo_root, monkeypatch):
    import zeus_client.constants as c

    monkeypatch.setattr(c, "CONFIG_PATH", patch_paths["config_path"])
    patch_paths["config_path"].unlink(missing_ok=True)
    cfg = _load_config_sync()
    assert cfg is not None


def test_load_config_invalid_json(patch_paths, monkeypatch):
    patch_paths["config_path"].write_text("{bad", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        _load_config_sync()


def test_save_config_strips_comment(patch_paths, sample_config):
    sample_config["_comment"] = "note"
    _save_config_sync(sample_config)
    saved = json.loads(patch_paths["config_path"].read_text())
    assert "_comment" not in saved