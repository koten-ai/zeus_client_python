"""Shared pytest fixtures for zeus_client tests."""

import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DATA = REPO_ROOT / "src" / "data"


@pytest.fixture
def respx_mock():
    """Activate respx routing for tests that mock outbound httpx calls."""
    import respx

    with respx.mock:
        yield


@pytest.fixture
def repo_root():
    return REPO_ROOT


@pytest.fixture
def sample_config():
    return {
        "catalog_batch_hash": "",
        "zeus": {
            "url": "http://zeus.test:8080",
            "auth_mode": "none",
        },
        "llm_provider": {
            "label": "xAI Grok",
            "base_url": "https://api.x.ai/v1",
            "api_key": "sk-test",
            "models": ["grok-4"],
        },
        "default_api_version": "v2",
        "default_mode": "analytics",
        "default_sample": "beer-sample",
        "samples": {
            "beer-sample": {
                "bucket": "beer-sample",
                "scope": "_default",
                "collection": "_default",
            },
        },
    }


@pytest.fixture
def patch_paths(monkeypatch, tmp_path, sample_config):
    """Isolate config and catalog dirs to tmp_path."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(sample_config), encoding="utf-8")
    bundled_chat_req_dir = tmp_path / "bundled_chat_requests"
    user_chat_req_dir = tmp_path / "chat_requests"
    src_chat = PACKAGE_DATA / "chat_requests"
    if src_chat.is_dir():
        shutil.copytree(src_chat, bundled_chat_req_dir)
    else:
        bundled_chat_req_dir.mkdir(parents=True)
    user_chat_req_dir.mkdir(parents=True, exist_ok=True)
    chat_log = tmp_path / "chats.jsonl"
    example_config = tmp_path / "config.example.json"
    example_config.write_text("{}", encoding="utf-8")
    user_config_dir = tmp_path

    def _user_chat_requests_dir():
        return user_chat_req_dir

    for target in (
        "zeus_client.constants",
        "zeus_client.config",
        "zeus_client.zeus.catalog",
        "zeus_client.zeus.sync",
    ):
        monkeypatch.setattr(f"{target}.CONFIG_PATH", config_path, raising=False)
        monkeypatch.setattr(f"{target}.EXAMPLE_CONFIG_PATH", example_config, raising=False)
        monkeypatch.setattr(f"{target}.CHAT_REQ_DIR", bundled_chat_req_dir, raising=False)
        monkeypatch.setattr(f"{target}.CHAT_LOG_PATH", chat_log, raising=False)
        monkeypatch.setattr(f"{target}.BASE_DIR", user_config_dir, raising=False)
        monkeypatch.setattr(f"{target}.USER_CONFIG_DIR", user_config_dir, raising=False)
        monkeypatch.setattr(
            f"{target}.user_chat_requests_dir", _user_chat_requests_dir, raising=False
        )

    return {
        "config_path": config_path,
        "chat_req_dir": bundled_chat_req_dir,
        "user_chat_req_dir": user_chat_req_dir,
        "chat_log": chat_log,
    }


@pytest.fixture
async def http_client():
    """Initialise the shared httpx client for modules that call client()."""
    import zeus_client.http_client as hc

    await hc.init_http()
    yield hc.client()
    await hc.close_http()


@pytest.fixture
def reset_auth_cache():
    import zeus_client.zeus.auth as auth

    auth._SESSION_CACHE.clear()
    yield
    auth._SESSION_CACHE.clear()
