"""RuntimeConfig loader / profile / secrets tests (ZCP-7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config import (
    apply_profile,
    list_profiles,
    load_runtime_config,
)
from zeus_client.config.models import RuntimeConfig, ZeusEndpointConfig
from zeus_client.domain.errors import ConfigError, ErrorCode


def test_ai_process_result_package_default_true() -> None:
    cfg = RuntimeConfig()
    assert cfg.settings.ai_process_result is True


def test_load_from_tmp_json(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "zeus": {"url": "http://example:8080", "auth_mode": "none"},
                "target": {"bucket": "b1", "scope": "s1", "collection": "c1"},
                "settings": {"ai_process_result": True, "max_rounds": 4},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_runtime_config(p, profile="development", env={})
    assert cfg.zeus.url == "http://example:8080"
    assert cfg.target.bucket == "b1"
    assert cfg.settings.max_rounds == 4
    assert cfg.profile == "development"
    assert cfg.debug.capture_bodies is True  # dev profile


def test_env_overrides_url_and_bucket(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "zeus": {
                    "url": "http://file:1",
                    "auth_mode": "basic",
                    "username": "admin",
                    "password_env": "ZEUS_PASSWORD",
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_runtime_config(
        p,
        profile="production",
        env={
            "ZEUS_CLIENT_URL": "http://env:9090",
            "ZEUS_CLIENT_BUCKET": "yelp-demo",
            "ZEUS_CLIENT_AI_PROCESS_RESULT": "false",
        },
    )
    assert cfg.zeus.url == "http://env:9090"
    assert cfg.target.bucket == "yelp-demo"
    assert cfg.settings.ai_process_result is False
    assert cfg.profile == "production"
    assert cfg.debug.capture_bodies is False
    assert cfg.redaction.preview_max_chars == 2048


def test_profile_matrix() -> None:
    assert set(list_profiles()) == {"development", "production", "ci"}
    base = RuntimeConfig(
        zeus=ZeusEndpointConfig(auth_mode="basic", username="u", password_env="ZEUS_PASSWORD")
    )
    dev = apply_profile(base, "development")
    prod = apply_profile(base, "production")
    ci = apply_profile(base, "ci")
    assert dev.debug.capture_bodies is True
    assert prod.debug.capture_bodies is False
    assert ci.debug.capture_bodies is False
    assert dev.redaction.preview_max_chars > prod.redaction.preview_max_chars


def test_config_repr_and_public_dict_have_no_secret_values() -> None:
    cfg = RuntimeConfig()
    text = repr(cfg)
    assert "password=" not in text.lower() or "password_env" in text
    # api_key_env is a name, not a value — ensure no fake secret
    assert "sk-" not in text
    pub = cfg.to_public_dict()
    assert pub["llm"]["api_key_env"] == "XAI_API_KEY"
    assert "api_key" not in pub["llm"]


def test_missing_config_path_raises() -> None:
    with pytest.raises(ConfigError) as ei:
        load_runtime_config("/no/such/config.json", env={})
    assert ei.value.code is ErrorCode.CONFIG_PATH_NOT_FOUND


def test_example_config_loads() -> None:
    root = Path(__file__).resolve().parents[3]
    example = root / "config.example.json"
    assert example.is_file()
    raw = example.read_text(encoding="utf-8")
    assert 'password"' not in raw or "password_env" in raw
    assert "sk-" not in raw
    cfg = load_runtime_config(example, env={})
    assert cfg.zeus.url.startswith("http")
    assert cfg.settings.ai_process_result is True


def test_load_llm_roles_and_jobs_host(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "llm": {
                    "model": "fast-worker",
                    "api_key_env": "LLM_DEFAULT_KEY",
                    "roles": {
                        "orchestrator": {"model": "strong-planner", "api_key_env": "LLM_ORCH_KEY"},
                        "advisor": {"model": "strong-planner"},
                        "worker": {"model": "fast-worker", "api_key_env": "LLM_WORKER_KEY"},
                    },
                },
                "jobs": {
                    "host_url": "http://127.0.0.1:7090",
                    "models": {"worker": {"model": "fast-worker-v2"}},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_runtime_config(p, profile="development", env={})
    assert cfg.llm.roles["orchestrator"].model == "strong-planner"
    assert cfg.llm.roles["orchestrator"].api_key_env == "LLM_ORCH_KEY"
    assert cfg.llm.roles["advisor"].api_key_env == "LLM_DEFAULT_KEY"
    assert cfg.jobs.host_url == "http://127.0.0.1:7090"
    pub = cfg.to_public_dict()
    assert pub["llm"]["roles"]["orchestrator"]["api_key_env"] == "LLM_ORCH_KEY"
    assert "sk-" not in json.dumps(pub)
    dumped = json.dumps(pub["llm"])
    assert '"api_key"' not in dumped
    assert "api_key_env" in dumped


def test_config_example_json_loads_roles_and_jobs() -> None:
    p = Path(__file__).resolve().parents[3] / "config.example.json"
    cfg = load_runtime_config(p, profile="development", env={})
    assert cfg.llm.roles["orchestrator"].model == "strong-planner"
    assert cfg.llm.roles["orchestrator"].api_key_env == "LLM_ORCH_KEY"
    assert cfg.llm.roles["worker"].api_key_env == "LLM_WORKER_KEY"
    assert cfg.jobs.host_url is None
    pub = json.dumps(cfg.to_public_dict())
    assert "sk-" not in pub
    assert "api_key_env" in pub


def test_env_secret_store() -> None:
    store = EnvSecretStore(environ={"XAI_API_KEY": "secret-value", "EMPTY": ""})
    assert store.get("XAI_API_KEY") == "secret-value"
    assert store.get("EMPTY") is None
    assert store.get("MISSING") is None
    assert "secret-value" not in repr(store)
