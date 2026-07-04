"""Tests for chat_request sync from Zeus into the user config directory."""
import json

import httpx
import pytest
import respx

import zeus_client.zeus.catalog as catalog
from zeus_client.zeus.catalog import chat_request_path, load_chat_request
from zeus_client.zeus.sync import (
    resolve_sync_modes,
    resolve_sync_scopes,
    sync_chat_requests,
)

ZEUS_URL = "http://zeus.test:8080"
BUCKET = "beer-sample"
SCOPE = "_default"
BRIEF = "## SCOPE BRIEF\nscope: beer-sample/_default\nmode: analytics\n"


@pytest.fixture
def sample_config_with_contracts(sample_config):
    cfg = dict(sample_config)
    cfg["zeus"] = dict(cfg["zeus"])
    cfg["zeus"]["scope_contracts"] = {
        f"{BUCKET}/{SCOPE}": {
            "analytics": {"contract_id": "c1", "contract_hash": "md5:abc"},
        },
    }
    return cfg


def test_resolve_sync_scopes_from_samples(sample_config):
    scopes = resolve_sync_scopes(sample_config, sample_config["zeus"])
    assert scopes == [(BUCKET, SCOPE)]


def test_resolve_sync_scopes_explicit(sample_config):
    cfg = {
        **sample_config,
        "chat_requests_sync": {"scopes": ["travel-sample/_default", "beer-sample/_default"]},
    }
    scopes = resolve_sync_scopes(cfg, {})
    assert scopes == [("beer-sample", "_default"), ("travel-sample", "_default")]


def test_resolve_sync_modes_auto(sample_config_with_contracts):
    modes = resolve_sync_modes(sample_config_with_contracts, BUCKET, SCOPE)
    assert "default" in modes
    assert "analytics" in modes


def test_resolve_sync_modes_explicit(sample_config):
    cfg = {**sample_config, "chat_requests_sync": {"modes": ["analytics", "code"]}}
    modes = resolve_sync_modes(cfg, BUCKET, SCOPE)
    assert modes == ["analytics", "code"]


def test_chat_request_path_prefers_synced_scope_dir(patch_paths, monkeypatch):
    user_dir = patch_paths["user_chat_req_dir"]
    scope_dir = user_dir / "beer-sample__default"
    scope_dir.mkdir(parents=True)
    synced = scope_dir / "chat_request_analytics_v2.json"
    synced.write_text("{}", encoding="utf-8")
    path = chat_request_path("v2", "analytics", bucket=BUCKET, scope=SCOPE)
    assert path == synced


@pytest.mark.asyncio
@respx.mock
async def test_sync_chat_requests_writes_scope_files(
    patch_paths, http_client, sample_config_with_contracts,
):
    live_analytics = {
        "messages": [{"role": "system", "content": f"rules\n{BRIEF}"}],
        "verbs": [{"name": "find"}],
    }
    live_default = {
        "messages": [{"role": "system", "content": f"base\n{BRIEF}"}],
        "verbs": [{"name": "get"}],
    }

    def _handler(request):
        mode = request.url.params.get("mode")
        if mode == "analytics":
            return httpx.Response(200, json=live_analytics)
        return httpx.Response(200, json=live_default)

    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(side_effect=_handler)

    result = await sync_chat_requests(sample_config_with_contracts, force=True)
    user_dir = patch_paths["user_chat_req_dir"]
    scope_dir = user_dir / "beer-sample__default"

    assert not result.errors
    assert len(result.synced) >= 2
    analytics_path = scope_dir / "chat_request_analytics_v2.json"
    default_path = scope_dir / "chat_request_v2.json"
    assert analytics_path.is_file()
    assert default_path.is_file()
    analytics_doc = json.loads(analytics_path.read_text(encoding="utf-8"))
    assert "## SCOPE BRIEF" in analytics_doc["messages"][0]["content"]
    assert (user_dir / "manifest.json").is_file()


@pytest.mark.asyncio
@respx.mock
async def test_sync_chat_requests_skips_unchanged(
    patch_paths, http_client, sample_config_with_contracts,
):
    doc = {"messages": [{"role": "system", "content": f"rules\n{BRIEF}"}]}
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(200, json=doc),
    )

    first = await sync_chat_requests(
        {**sample_config_with_contracts, "chat_requests_sync": {"modes": ["analytics"]}},
        force=True,
    )
    assert len(first.synced) == 1
    assert not first.skipped

    second = await sync_chat_requests(
        {**sample_config_with_contracts, "chat_requests_sync": {"modes": ["analytics"]}},
    )
    assert not second.synced
    assert len(second.skipped) == 1


@pytest.mark.asyncio
@respx.mock
async def test_load_chat_request_uses_synced_without_live_fetch(
    patch_paths, http_client, sample_config_with_contracts,
):
    user_dir = patch_paths["user_chat_req_dir"]
    scope_dir = user_dir / "beer-sample__default"
    scope_dir.mkdir(parents=True)
    synced = {
        "messages": [{"role": "system", "content": f"offline\n{BRIEF}"}],
        "verbs": [{"name": "find"}],
    }
    (scope_dir / "chat_request_analytics_v2.json").write_text(
        json.dumps(synced), encoding="utf-8",
    )

    route = respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json")
    route.mock(return_value=httpx.Response(500, text="should not be called"))

    cat, src = await load_chat_request(
        ZEUS_URL, "v2", "analytics", BUCKET, SCOPE, {},
    )
    assert "## SCOPE BRIEF" in cat["messages"][0]["content"]
    assert "synced" in src
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_sync_chat_requests_collects_errors(
    patch_paths, http_client, sample_config_with_contracts,
):
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(500, text="fail"),
    )
    result = await sync_chat_requests(
        {**sample_config_with_contracts, "chat_requests_sync": {"modes": ["analytics"]}},
        force=True,
    )
    assert not result.synced
    assert len(result.errors) == 1
    assert "HTTP 500" in result.errors[0]["error"]