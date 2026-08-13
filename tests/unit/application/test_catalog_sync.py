"""Catalog sync preserve rules (ZCP-12 · port of V1 test_catalog_sync oracles)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.application.catalog_sync import (
    SyncResult,
    resolve_sync_modes,
    resolve_sync_scopes,
    should_preserve_local_catalog,
    sync_catalogs,
)
from zeus_client.domain.contract import compute_contract_hash, extract_stamped_hash


def test_resolve_sync_scopes_from_samples() -> None:
    cfg = {
        "samples": {
            "beer": {"bucket": "beer-sample", "scope": "_default"},
            "travel": {"bucket": "travel-sample", "scope": "_default"},
        }
    }
    assert resolve_sync_scopes(cfg) == [
        ("beer-sample", "_default"),
        ("travel-sample", "_default"),
    ]


def test_resolve_sync_scopes_explicit() -> None:
    cfg = {
        "chat_requests_sync": {
            "scopes": ["travel-sample/_default", "beer-sample/_default"],
        }
    }
    assert resolve_sync_scopes(cfg) == [
        ("beer-sample", "_default"),
        ("travel-sample", "_default"),
    ]


def test_resolve_sync_modes_auto_includes_contracts() -> None:
    cfg = {
        "scope_contracts": {
            "beer-sample/_default": {
                "analytics": {"contract_id": "c1", "contract_hash": "md5:abc"},
            }
        }
    }
    modes = resolve_sync_modes(cfg, "beer-sample", "_default")
    assert "default" in modes
    assert "analytics" in modes


def test_resolve_sync_modes_explicit() -> None:
    cfg = {"chat_requests_sync": {"modes": ["analytics", "code"]}}
    assert resolve_sync_modes(cfg, "b", "_default") == ["analytics", "code"]


def test_should_preserve_stamped_local_over_legacy_tools_remote() -> None:
    local = {
        "_format": "zeus.chat_request.v2",
        "contract": {"hash": "md5:stampedlocal00000000000000000001"},
        "_hash": "md5:stampedlocal00000000000000000001",
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "messages": [{"role": "system", "content": "stamped rules"}],
    }
    remote = {
        "_mode": "analytics",
        "tools": [{"type": "function", "function": {"name": "find_nodes"}}],
        "messages": [{"role": "system", "content": "legacy find_nodes catalog"}],
    }
    reason = should_preserve_local_catalog(local, remote)
    assert "preserve_stamped_local" in reason
    assert "tools-only" in reason or "V1" in reason


def test_should_preserve_consistent_local_over_inconsistent_remote() -> None:
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
    remote = {
        **base,
        "messages": [
            {
                "role": "system",
                "content": "stamped rules clean\n\n## SCOPE BRIEF\nscope material",
            }
        ],
        "contract": {
            "hash": "md5:5aacbf1d7a4d9d5de9436cdffbce050f",
            "builder": "base-4",
            "scope": "prototype/_unbound",
        },
        "_hash": "md5:5aacbf1d7a4d9d5de9436cdffbce050f",
        "verbs": [
            {"type": "function", "function": {"name": "find"}},
            {"type": "function", "function": {"name": "pipeline"}},
        ],
    }
    assert compute_contract_hash(remote) != extract_stamped_hash(remote)
    reason = should_preserve_local_catalog(local, remote)
    assert "preserve_stamped_local" in reason
    assert "disagrees with content hash" in reason


def test_should_not_preserve_when_local_unstamped() -> None:
    local = {"messages": [{"role": "system", "content": "x"}], "tools": []}
    remote = {
        "contract": {"hash": "md5:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "_format": "zeus.chat_request.v2",
        "messages": [{"role": "system", "content": "y"}],
    }
    assert should_preserve_local_catalog(local, remote) == ""


@pytest.mark.asyncio
async def test_sync_writes_scope_files_and_skips_unchanged(tmp_path: Path) -> None:
    user = tmp_path / "chat_requests"
    store = FsCatalogStore(root=user)

    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        return {
            "messages": [{"role": "system", "content": f"rules {mode}"}],
            "verbs": [{"type": "function", "function": {"name": "find"}}],
            "_format": "zeus.chat_request.v2",
        }

    cfg = {
        "samples": {"beer": {"bucket": "beer-sample", "scope": "_default"}},
        "chat_requests_sync": {"modes": ["analytics"]},
    }
    first = await sync_catalogs(cfg, store=store, fetch=fetch, force=True)
    assert isinstance(first, SyncResult)
    assert len(first.synced) == 1
    assert not first.errors
    path = user / "beer-sample__default" / "chat_request_analytics_v2.json"
    assert path.is_file()
    assert first.manifest_path is not None
    assert first.manifest_path.is_file()

    second = await sync_catalogs(cfg, store=store, fetch=fetch, force=False)
    assert not second.synced
    assert len(second.skipped) == 1


@pytest.mark.asyncio
async def test_sync_preserves_stamped_local_over_legacy_remote(tmp_path: Path) -> None:
    user = tmp_path / "chat_requests"
    scope = user / "beer-sample__default"
    scope.mkdir(parents=True)
    local = {
        "_format": "zeus.chat_request.v2",
        "contract": {"hash": "md5:stampedlocal00000000000000000001"},
        "_hash": "md5:stampedlocal00000000000000000001",
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "messages": [{"role": "system", "content": "stamped rules"}],
    }
    path = scope / "chat_request_analytics_v2.json"
    path.write_text(json.dumps(local), encoding="utf-8")
    store = FsCatalogStore(root=user)

    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        return {
            "_mode": "analytics",
            "tools": [{"type": "function", "function": {"name": "find_nodes"}}],
            "messages": [{"role": "system", "content": "legacy"}],
        }

    cfg = {
        "samples": {"beer": {"bucket": "beer-sample", "scope": "_default"}},
        "chat_requests_sync": {"modes": ["analytics"]},
    }
    result = await sync_catalogs(cfg, store=store, fetch=fetch, force=True)
    assert not result.synced
    assert len(result.skipped) == 1
    assert "preserve_stamped_local" in (result.skipped[0].get("reason") or "")
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["contract"]["hash"] == "md5:stampedlocal00000000000000000001"


@pytest.mark.asyncio
async def test_sync_collects_fetch_errors(tmp_path: Path) -> None:
    store = FsCatalogStore(root=tmp_path / "user")

    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        raise RuntimeError("HTTP 500: fail")

    cfg = {
        "samples": {"beer": {"bucket": "beer-sample", "scope": "_default"}},
        "chat_requests_sync": {"modes": ["analytics"]},
    }
    result = await sync_catalogs(cfg, store=store, fetch=fetch, force=True)
    assert not result.synced
    assert len(result.errors) == 1
    assert "HTTP 500" in result.errors[0]["error"]


@pytest.mark.asyncio
async def test_catalog_api_load_from_store(tmp_path: Path) -> None:
    from zeus_client.api.catalog import CatalogAPI
    from zeus_client.config.models import DataTarget, RuntimeConfig
    from zeus_client.runtime import ZeusRuntime

    user = tmp_path / "user"
    scope = user / "yelp-data__default"
    scope.mkdir(parents=True)
    body = {
        "messages": [{"role": "system", "content": "hi"}],
        "verbs": [{"type": "function", "function": {"name": "find"}}],
    }
    (scope / "chat_request_analytics_v2.json").write_text(json.dumps(body), encoding="utf-8")
    store = FsCatalogStore(root=user)
    cfg = RuntimeConfig(
        target=DataTarget(bucket="yelp-data", scope="_default", collection="_default"),
        chat_requests_dir=str(user),
    )
    rt = ZeusRuntime(cfg, catalog=store)
    api = CatalogAPI(rt)
    loaded = await api.load(mode="analytics")
    assert loaded.body["messages"][0]["content"] == "hi"
    listed = await api.list()
    assert any(e.get("mode") == "analytics" for e in listed)
