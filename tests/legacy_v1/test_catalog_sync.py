"""Tests for chat_request sync from Zeus into the user config directory."""

import json

import httpx
import pytest
import respx
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
    patch_paths,
    http_client,
    sample_config_with_contracts,
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
    patch_paths,
    http_client,
    sample_config_with_contracts,
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
    patch_paths,
    http_client,
    sample_config_with_contracts,
):
    user_dir = patch_paths["user_chat_req_dir"]
    scope_dir = user_dir / "beer-sample__default"
    scope_dir.mkdir(parents=True)
    synced = {
        "messages": [{"role": "system", "content": f"offline\n{BRIEF}"}],
        "verbs": [{"name": "find"}],
    }
    (scope_dir / "chat_request_analytics_v2.json").write_text(
        json.dumps(synced),
        encoding="utf-8",
    )

    route = respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json")
    route.mock(return_value=httpx.Response(500, text="should not be called"))

    cat, src = await load_chat_request(
        ZEUS_URL,
        "v2",
        "analytics",
        BUCKET,
        SCOPE,
        {},
    )
    assert "## SCOPE BRIEF" in cat["messages"][0]["content"]
    assert "synced" in src
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_sync_chat_requests_collects_errors(
    patch_paths,
    http_client,
    sample_config_with_contracts,
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


@pytest.mark.asyncio
@respx.mock
async def test_sync_preserves_stamped_local_over_legacy_tools_remote(
    patch_paths,
    http_client,
    sample_config_with_contracts,
):
    """Do not clobber a Verify-stamped V2 catalog with an unstamped tools-only pull."""
    user_dir = patch_paths["user_chat_req_dir"]
    scope_dir = user_dir / "beer-sample__default"
    scope_dir.mkdir(parents=True)
    local = {
        "_format": "zeus.chat_request.v2",
        "contract": {"hash": "md5:stampedlocal00000000000000000001"},
        "_hash": "md5:stampedlocal00000000000000000001",
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "messages": [{"role": "system", "content": "stamped rules"}],
    }
    path = scope_dir / "chat_request_analytics_v2.json"
    path.write_text(json.dumps(local), encoding="utf-8")

    remote = {
        "_mode": "analytics",
        "tools": [{"type": "function", "function": {"name": "find_nodes"}}],
        "messages": [{"role": "system", "content": "legacy find_nodes catalog"}],
    }
    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(200, json=remote),
    )

    result = await sync_chat_requests(
        {**sample_config_with_contracts, "chat_requests_sync": {"modes": ["analytics"]}},
        force=True,
    )
    assert not result.synced
    assert len(result.skipped) == 1
    assert "preserve_stamped_local" in (result.skipped[0].get("reason") or "")
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["contract"]["hash"] == "md5:stampedlocal00000000000000000001"
    assert kept.get("verbs")


@pytest.mark.asyncio
@respx.mock
async def test_sync_preserves_consistent_local_over_inconsistent_remote_stamp(
    patch_paths,
    http_client,
    sample_config_with_contracts,
):
    """Keep a Verify-consistent local file when remote still has a stale prototype stamp."""
    from zeus_client.contract_hash import compute_contract_hash, extract_stamped_hash

    user_dir = patch_paths["user_chat_req_dir"]
    scope_dir = user_dir / "beer-sample__default"
    scope_dir.mkdir(parents=True)
    base = {
        "_format": "zeus.chat_request.v2",
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "messages": [{"role": "system", "content": "stamped rules clean"}],
    }
    good_h = compute_contract_hash(base)
    local = {
        **base,
        "contract": {"hash": good_h, "builder": "CatalogForContract@verify"},
        "_hash": good_h,
    }
    path = scope_dir / "chat_request_analytics_v2.json"
    path.write_text(json.dumps(local), encoding="utf-8")

    remote = {
        **base,
        "messages": [
            {
                "role": "system",
                "content": "stamped rules clean\n\n## SCOPE BRIEF\nscope material",
            }
        ],
        # Prototype / base-pack stamp that no longer matches locked content after edits.
        "contract": {
            "hash": "md5:5aacbf1d7a4d9d5de9436cdffbce050f",
            "builder": "base-4",
            "scope": "prototype/_unbound",
        },
        "_hash": "md5:5aacbf1d7a4d9d5de9436cdffbce050f",
    }
    # Force locked-content drift so remote stamp is inconsistent even after brief strip.
    remote["verbs"] = [
        {"type": "function", "function": {"name": "find"}},
        {"type": "function", "function": {"name": "pipeline"}},
    ]
    assert compute_contract_hash(remote) != extract_stamped_hash(remote)

    respx.get(f"{ZEUS_URL}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(200, json=remote),
    )

    result = await sync_chat_requests(
        {**sample_config_with_contracts, "chat_requests_sync": {"modes": ["analytics"]}},
        force=True,
    )
    assert not result.synced
    assert len(result.skipped) == 1
    reason = result.skipped[0].get("reason") or ""
    assert "preserve_stamped_local" in reason
    assert "disagrees with content hash" in reason
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["contract"]["hash"] == good_h
    assert kept.get("verbs") == local["verbs"]
