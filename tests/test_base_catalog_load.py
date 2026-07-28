"""base-5 catalog load by base_id (ZC-WISH-001)."""
from pathlib import Path

import pytest

from zeus_client.zeus.base_catalog import (
    find_base_catalog_path,
    list_base_catalogs,
    load_base_catalog,
    parse_catalog_filename,
)

FIX = Path(__file__).parent / "fixtures" / "base-5.3"


def test_parse_catalog_filename_base_53():
    meta = parse_catalog_filename("chat_request_analytics_base-5.3.json")
    assert meta == {
        "mode": "analytics",
        "base_id": "base-5.3",
        "file": "chat_request_analytics_base-5.3.json",
    }


def test_parse_catalog_filename_rejects_legacy_v2():
    assert parse_catalog_filename("chat_request_analytics_v2.json") is None


def test_load_base_53_analytics_lineage():
    doc = load_base_catalog(base_id="base-5.3", mode="analytics", search_dirs=[FIX])
    assert doc["_lineage"]["base_id"] == "base-5.3"
    assert doc["_format"] == "zeus.chat_request.v2"
    assert "messages" in doc


def test_list_base_catalogs_finds_fixture():
    found = list_base_catalogs([FIX])
    assert any(e["base_id"] == "base-5.3" and e["mode"] == "analytics" for e in found)


def test_load_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_base_catalog(base_id="base-5.3", mode="nope", search_dirs=[FIX])


def test_lineage_mismatch_raises(tmp_path):
    import json
    p = tmp_path / "chat_request_analytics_base-5.3.json"
    p.write_text(json.dumps({
        "_lineage": {"base_id": "base-5.2"},
        "messages": [{"role": "system", "content": "x"}],
    }))
    with pytest.raises(ValueError, match="lineage"):
        load_base_catalog(base_id="base-5.3", mode="analytics", search_dirs=[tmp_path])


def test_find_path():
    path = find_base_catalog_path(base_id="base-5.3", mode="analytics", search_dirs=[FIX])
    assert path is not None
    assert path.name.endswith("base-5.3.json")
