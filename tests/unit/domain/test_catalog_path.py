"""Catalog path resolution — fail-closed, no sibling-scope rglob (ZCP-12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zeus_client_v2.domain.catalog import (
    chat_request_filename,
    merge_scope_brief,
    resolve_catalog_path,
    scope_chat_requests_subdir,
)
from zeus_client_v2.domain.errors import CatalogError, ErrorCode
from zeus_client_v2.ports import CatalogKey


def test_scope_subdir_strips_leading_underscore() -> None:
    assert scope_chat_requests_subdir("beer-sample", "_default") == "beer-sample__default"
    assert scope_chat_requests_subdir("yelp-data", "inventory") == "yelp-data__inventory"


def test_chat_request_filename() -> None:
    assert chat_request_filename("default") == "chat_request_v2.json"
    assert chat_request_filename("") == "chat_request_v2.json"
    assert chat_request_filename("analytics") == "chat_request_analytics_v2.json"


def test_resolve_prefers_scope_dir(tmp_path: Path) -> None:
    user = tmp_path / "user"
    scope = user / "beer-sample__default"
    scope.mkdir(parents=True)
    target = scope / "chat_request_analytics_v2.json"
    target.write_text("{}", encoding="utf-8")
    # Sibling + general must not win when scope file exists
    sib = user / "yelp-data__default"
    sib.mkdir()
    (sib / "chat_request_analytics_v2.json").write_text('{"wrong":1}', encoding="utf-8")
    (user / "chat_request_analytics_v2.json").write_text('{"general":1}', encoding="utf-8")

    path = resolve_catalog_path(
        mode="analytics",
        bucket="beer-sample",
        scope="_default",
        user_dir=user,
    )
    assert path == target


def test_resolve_does_not_pick_sibling_scope_when_target_missing(tmp_path: Path) -> None:
    """Empty yelp-demo__default must NOT fall through to yelp-data__default via rglob."""
    user = tmp_path / "user"
    (user / "yelp-demo__default").mkdir(parents=True)
    sib = user / "yelp-data__default"
    sib.mkdir()
    (sib / "chat_request_analytics_v2.json").write_text(
        json.dumps({"from": "sibling"}), encoding="utf-8"
    )

    path = resolve_catalog_path(
        mode="analytics",
        bucket="yelp-demo",
        scope="_default",
        user_dir=user,
    )
    assert path is None


def test_resolve_user_general_top_level_only(tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    general = user / "chat_request_analytics_v2.json"
    general.write_text("{}", encoding="utf-8")
    # Nested under unrelated dir name without __ must still not be found via rglob —
    # only direct children of user root count as general.
    nested = user / "other" / "nested"
    nested.mkdir(parents=True)
    (nested / "chat_request_analytics_v2.json").write_text('{"nested":1}', encoding="utf-8")

    path = resolve_catalog_path(
        mode="analytics",
        bucket="beer-sample",
        scope="_default",
        user_dir=user,
    )
    assert path == general


def test_resolve_bundled_fallback(tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    bfile = bundled / "chat_request_analytics_v2.json"
    bfile.write_text("{}", encoding="utf-8")

    path = resolve_catalog_path(
        mode="analytics",
        bucket="x",
        scope="_default",
        user_dir=user,
        bundled_dir=bundled,
    )
    assert path == bfile


def test_resolve_default_mode_filename(tmp_path: Path) -> None:
    user = tmp_path / "user"
    scope = user / "beer-sample__default"
    scope.mkdir(parents=True)
    p = scope / "chat_request_v2.json"
    p.write_text("{}", encoding="utf-8")
    path = resolve_catalog_path(
        mode="default",
        bucket="beer-sample",
        scope="_default",
        user_dir=user,
    )
    assert path == p


def test_merge_scope_brief_rstrips_and_appends() -> None:
    doc = {
        "messages": [{"role": "system", "content": "rules only\n"}],
        "instructions": {"system_prompt": "marker only\n"},
    }
    out = merge_scope_brief(doc, "## SCOPE BRIEF\nscope: demo/_default")
    assert out["messages"][0]["content"].startswith("rules only\n\n## SCOPE BRIEF")
    assert "marker only\n\n## SCOPE BRIEF" in out["instructions"]["system_prompt"]
    # original unchanged
    assert doc["messages"][0]["content"] == "rules only\n"


def test_fs_store_load_raises_catalog_not_found(tmp_path: Path) -> None:
    from zeus_client_v2.adapters.catalog_fs.store import FsCatalogStore

    store = FsCatalogStore(root=tmp_path / "user", bundled_dir=tmp_path / "bundled")
    (tmp_path / "user").mkdir()
    (tmp_path / "bundled").mkdir()
    with pytest.raises(CatalogError) as ei:
        store.load(CatalogKey(mode="analytics", bucket="a", scope="_default"))
    assert ei.value.code == ErrorCode.CATALOG_NOT_FOUND


def test_fs_store_load_heals_and_returns_document(tmp_path: Path) -> None:
    from zeus_client_v2.adapters.catalog_fs.store import FsCatalogStore
    from zeus_client_v2.domain.contract import compute_contract_hash

    user = tmp_path / "user"
    scope = user / "beer-sample__default"
    scope.mkdir(parents=True)
    body = {
        "messages": [{"role": "system", "content": "rules only"}],
        "verbs": [{"type": "function", "function": {"name": "find"}}],
    }
    h = compute_contract_hash(body)
    body["contract"] = {"hash": h}
    (scope / "chat_request_analytics_v2.json").write_text(
        json.dumps(body), encoding="utf-8"
    )
    store = FsCatalogStore(root=user)
    doc = store.load(CatalogKey(mode="analytics", bucket="beer-sample", scope="_default"))
    assert doc.contract_hash == h
    assert doc.body["messages"][0]["content"] == "rules only"
    assert doc.path is not None
    assert "beer-sample__default" in doc.path
