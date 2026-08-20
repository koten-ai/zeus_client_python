"""base_id / lineage catalog load (CHECKLIST A · ZC-WISH-001)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.domain.catalog import (
    chat_request_filename,
    check_lineage,
    list_catalog_entries,
    mode_from_filename,
    parse_catalog_filename,
    resolve_catalog_path,
)
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.ports import CatalogKey

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "base-5.3"


def test_parse_catalog_filename_base_53() -> None:
    meta = parse_catalog_filename("chat_request_analytics_base-5.3.json")
    assert meta == {
        "mode": "analytics",
        "base_id": "base-5.3",
        "file": "chat_request_analytics_base-5.3.json",
    }


def test_parse_catalog_filename_cus() -> None:
    meta = parse_catalog_filename("chat_request_analytics_cus-3.json")
    assert meta is not None
    assert meta["base_id"] == "cus-3"
    assert meta["mode"] == "analytics"


def test_parse_catalog_filename_rejects_legacy_v2() -> None:
    assert parse_catalog_filename("chat_request_analytics_v2.json") is None


def test_mode_from_filename_lineage() -> None:
    assert mode_from_filename("chat_request_analytics_base-5.3.json") == "analytics"
    assert chat_request_filename("analytics", "base-5.3") == (
        "chat_request_analytics_base-5.3.json"
    )


def test_resolve_and_load_base_53() -> None:
    path = resolve_catalog_path(
        mode="analytics",
        bucket="x",
        scope="_default",
        user_dir=FIX,
        base_id="base-5.3",
    )
    assert path is not None
    assert path.name.endswith("base-5.3.json")
    store = FsCatalogStore(root=FIX)
    doc = store.load_rich(
        CatalogKey(mode="analytics", bucket="x", scope="_default", base_id="base-5.3")
    )
    assert doc.base_id == "base-5.3"
    assert doc.lineage_id == "base-5.3"
    assert doc.body["_format"] == "zeus.chat_request.v2"
    assert "messages" in doc.body
    assert doc.contract_hash  # stamped fixture — extract only, never invented


def test_list_includes_lineage_and_stats() -> None:
    found = list_catalog_entries(FIX)
    hit = next(e for e in found if e.get("base_id") == "base-5.3")
    assert hit["mode"] == "analytics"
    assert hit["stamp_present"] == "true"
    assert int(hit["verb_count"]) > 0
    assert hit["lineage_id"] == "base-5.3"


def test_lineage_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "chat_request_analytics_base-5.3.json"
    p.write_text(
        json.dumps(
            {
                "_lineage": {"base_id": "base-5.2"},
                "messages": [{"role": "system", "content": "x"}],
            }
        ),
        encoding="utf-8",
    )
    store = FsCatalogStore(root=tmp_path)
    with pytest.raises(CatalogError) as ei:
        store.load(
            CatalogKey(
                mode="analytics",
                bucket="x",
                scope="_default",
                base_id="base-5.3",
            )
        )
    assert ei.value.code == ErrorCode.CATALOG_LINEAGE_UNKNOWN


def test_missing_lineage_refused(tmp_path: Path) -> None:
    p = tmp_path / "chat_request_analytics_base-5.3.json"
    p.write_text(
        json.dumps({"messages": [{"role": "system", "content": "x"}]}),
        encoding="utf-8",
    )
    store = FsCatalogStore(root=tmp_path)
    with pytest.raises(CatalogError) as ei:
        store.load(
            CatalogKey(
                mode="analytics",
                bucket="x",
                scope="_default",
                base_id="base-5.3",
            )
        )
    assert ei.value.code == ErrorCode.CATALOG_LINEAGE_UNKNOWN


def test_check_lineage_rejects_bad_id_shape() -> None:
    with pytest.raises(CatalogError) as ei:
        check_lineage({}, "not-a-base")
    assert ei.value.code == ErrorCode.CATALOG_LINEAGE_UNKNOWN


def test_legacy_v2_path_unchanged_when_base_id_omitted(tmp_path: Path) -> None:
    scope = tmp_path / "beer-sample__default"
    scope.mkdir(parents=True)
    target = scope / "chat_request_analytics_v2.json"
    target.write_text("{}", encoding="utf-8")
    path = resolve_catalog_path(
        mode="analytics",
        bucket="beer-sample",
        scope="_default",
        user_dir=tmp_path,
    )
    assert path == target


def test_base_id_does_not_rglob_sibling_scope(tmp_path: Path) -> None:
    want = tmp_path / "yelp-demo__default"
    want.mkdir()
    sib = tmp_path / "yelp-data__default"
    sib.mkdir()
    (sib / "chat_request_analytics_base-5.3.json").write_text(
        json.dumps({"_lineage": {"base_id": "base-5.3"}}),
        encoding="utf-8",
    )
    path = resolve_catalog_path(
        mode="analytics",
        bucket="yelp-demo",
        scope="_default",
        user_dir=tmp_path,
        base_id="base-5.3",
    )
    assert path is None
