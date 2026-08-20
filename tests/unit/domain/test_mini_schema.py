"""MINI-SCHEMA parse (CHECKLIST A · catalog.mini_schema)."""

from __future__ import annotations

from tests.fixtures.catalog_brief import base_chat_req

from zeus_client.domain.mini_schema import (
    MISSING_MINI_SCHEMA,
    classify_mini_schema,
    get_mini_schema,
)


def test_get_mini_schema_structure() -> None:
    s = get_mini_schema(base_chat_req(), values=False)
    assert s["scope"] == "beer-sample/_default"
    assert s["mode"] == "auto"
    assert set(s["entity_types"]) == {"Beer", "Brewery"}
    beer = s["entity_types"]["Beer"]
    assert beer["field_count"] == 8
    assert beer["fields"]["abv"] == {"kind": "number", "indexed": "gsi", "filterable": True}
    assert beer["fields"]["category"]["filterable"] is False
    assert beer["fields"]["brewery_id"]["fk_to"] == "Brewery"
    assert "examples" not in beer["fields"]["brewery_id"]
    brew = s["entity_types"]["Brewery"]
    assert brew["inverse_fks"] == [
        {"from_entity": "Beer", "from_path": "brewery_id", "kind": "entity_fk"}
    ]


def test_get_mini_schema_values() -> None:
    s = get_mini_schema(base_chat_req(), values=True)
    assert s["entity_types"]["Beer"]["fields"]["brewery_id"]["examples"] == ["coopers_brewery"]


def test_get_mini_schema_no_brief_is_empty() -> None:
    s = get_mini_schema({"messages": [{"role": "system", "content": "no brief here"}]})
    assert s == {"scope": "", "mode": "", "entity_types": {}}


def test_classify_mini_schema_missing() -> None:
    got = classify_mini_schema(
        get_mini_schema({"messages": [{"role": "system", "content": "no brief here"}]})
    )
    assert got["result"] is False
    assert got["error_class"] == MISSING_MINI_SCHEMA


def test_classify_mini_schema_present() -> None:
    got = classify_mini_schema(get_mini_schema(base_chat_req()))
    assert got["result"] is True
    assert got["error_class"] is None
    assert "Beer" in got["entity_types"]
