"""Tests for structured zeus_data extraction from agent traces."""
import copy

from zeus_client.agent.response import (
    StructuredAgentResponse,
    extract_structured_response,
    filter_rows_to_schema,
    resolve_field_allowlist,
)
from tests.fixtures.catalog_brief import base_chat_req


def _trace_with_find(items, entity_type="Beer"):
    return {
        "steps": [
            {
                "round": 2,
                "type": "return",
                "args": {
                    "summary": "Two beers found.",
                    "decomposition": {
                        "intent": "list beers",
                        "targets": [{"entity_type": entity_type}],
                    },
                },
            },
        ],
        "tool_calls": [
            {
                "round": 1,
                "name": "find",
                "args": {"entity_type": entity_type, "return": "rows"},
                "status": 200,
                "result_json": {"result": {"items": items}},
            },
        ],
    }


def test_find_items_extracted():
    items = [
        {"id": "n_1", "name": "IPA", "abv": 6.5, "unknown_field": "x"},
        {"id": "n_2", "name": "Stout", "abv": 5.0},
    ]
    trace = _trace_with_find(items)
    resp = extract_structured_response("Two beers found.", trace, base_chat_req())

    assert isinstance(resp, StructuredAgentResponse)
    assert resp.answer == "Two beers found."
    assert resp.source_tool == "find"
    assert resp.entity_type == "Beer"
    assert len(resp.zeus_data) == 2
    assert resp.zeus_data[0]["id"] == "n_1"
    assert resp.zeus_data[0]["name"] == "IPA"
    assert "unknown_field" not in resp.zeus_data[0]
    assert any("dropped unknown field 'unknown_field'" in w for w in resp.warnings)
    assert resp.decomposition["intent"] == "list beers"


def test_pipeline_step_rows():
    trace = {
        "steps": [{"type": "return", "args": {"summary": "done"}}],
        "tool_calls": [
            {
                "name": "pipeline",
                "status": 200,
                "args": {
                    "steps": [{"verb": "find", "as": "rows", "entity_type": "Beer"}],
                    "return": ["rows"],
                },
                "result_json": {
                    "result": {
                        "rows": [
                            {"id": "n_10", "name": "Lager", "abv": 4.5},
                        ],
                    },
                },
            },
        ],
    }
    resp = extract_structured_response("done", trace, base_chat_req())
    assert resp.source_tool == "pipeline"
    assert resp.entity_type == "Beer"
    assert resp.zeus_data == [{"id": "n_10", "name": "Lager", "abv": 4.5}]


def test_terminating_pipeline_data_envelope():
    trace = {
        "steps": [{"type": "return", "args": {"summary": "hotels"}}],
        "tool_calls": [
            {
                "name": "pipeline",
                "status": 200,
                "args": {"steps": [], "summary": "hotels"},
                "result_json": {
                    "data": [
                        {"id": "n_h1", "name": "Hotel 1"},
                    ],
                },
            },
        ],
    }
    cr = copy.deepcopy(base_chat_req())
    cr["guidance"] = {
        "injections": {
            "output_schema": {"Hotel": ["id", "name"]},
        },
    }
    resp = extract_structured_response("hotels", trace, cr, output_schema={"Hotel": ["id", "name"]})
    assert resp.zeus_data == [{"id": "n_h1", "name": "Hotel 1"}]
    assert resp.source_tool == "pipeline"


def test_legacy_rows_shape():
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "find",
                "status": 200,
                "args": {"entity_type": "Beer"},
                "result_json": {"rows": [{"id": "n_3", "name": "Porter", "abv": 5.5}]},
            },
        ],
    }
    resp = extract_structured_response("", trace, base_chat_req())
    assert resp.zeus_data[0]["name"] == "Porter"


def test_fk_dotted_field_kept():
    rows = [{"id": "n_1", "name": "IPA", "brewery_id.name": "Coopers"}]
    allowed, fk_prefixes, _ = resolve_field_allowlist(base_chat_req(), "Beer")
    filtered, warnings = filter_rows_to_schema(rows, allowed, fk_prefixes, "Beer")
    assert filtered[0]["brewery_id.name"] == "Coopers"
    assert not warnings


def test_output_schema_override():
    rows = [{"id": "n_1", "name": "Hotel 1", "rating": 4.5, "secret": "x"}]
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "find",
                "status": 200,
                "args": {"entity_type": "Hotel"},
                "result_json": {"result": {"items": rows}},
            },
        ],
    }
    override = {"entity_type": "Hotel", "fields": ["id", "name", "rating"]}
    resp = extract_structured_response("hotels", trace, base_chat_req(), output_schema=override)
    assert resp.zeus_data == [{"id": "n_1", "name": "Hotel 1", "rating": 4.5}]
    assert any("secret" in w for w in resp.warnings)


def test_injection_output_schema_from_chat_req():
    cr = copy.deepcopy(base_chat_req())
    cr["guidance"] = {
        "injections": {
            "output_schema": {"Beer": ["id", "name"]},
        },
    }
    rows = [{"id": "n_1", "name": "IPA", "abv": 6.0}]
    trace = _trace_with_find(rows)
    resp = extract_structured_response("ok", trace, cr)
    assert resp.zeus_data == [{"id": "n_1", "name": "IPA"}]
    assert any("abv" in w for w in resp.warnings)


def test_no_data_tool_calls_empty_zeus_data():
    trace = {
        "steps": [{"type": "return", "args": {"summary": "no data"}}],
        "tool_calls": [],
    }
    resp = extract_structured_response("no data", trace, base_chat_req())
    assert resp.zeus_data == []
    assert resp.return_payload["summary"] == "no data"


def test_no_mini_schema_warns_and_empty_data():
    trace = _trace_with_find([{"id": "n_1", "foo": "bar"}])
    cr = {"messages": [{"role": "system", "content": "no brief"}]}
    resp = extract_structured_response("x", trace, cr)
    assert resp.zeus_data == []
    assert any("no MINI-SCHEMA" in w for w in resp.warnings)


def test_evidence_fallback():
    trace = {
        "steps": [
            {
                "type": "return",
                "args": {
                    "summary": "from evidence",
                    "decomposition": {"targets": [{"entity_type": "Beer"}]},
                    "evidence": [{"id": "n_9", "name": "Ale", "abv": 5.0}],
                },
            },
        ],
        "tool_calls": [],
    }
    resp = extract_structured_response("from evidence", trace, base_chat_req())
    assert resp.source_tool == "return"
    assert resp.zeus_data[0]["name"] == "Ale"


def test_skips_failed_tool_calls():
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "find",
                "status": 500,
                "args": {"entity_type": "Beer"},
                "result_json": {"result": {"items": [{"id": "n_bad"}]}},
            },
            {
                "name": "find",
                "status": 200,
                "args": {"entity_type": "Beer"},
                "result_json": {"result": {"items": [{"id": "n_good", "name": "Good", "abv": 5}]}},
            },
        ],
    }
    resp = extract_structured_response("", trace, base_chat_req())
    assert resp.zeus_data[0]["id"] == "n_good"


def test_entity_type_from_decomposition_when_tool_lacks_it():
    trace = {
        "steps": [
            {
                "type": "return",
                "args": {
                    "summary": "ok",
                    "decomposition": {"targets": [{"entity_type": "Beer"}]},
                },
            },
        ],
        "tool_calls": [
            {
                "name": "project",
                "status": 200,
                "args": {"fields": ["name", "abv"]},
                "result_json": {"result": {"rows": [{"id": "n_1", "name": "X", "abv": 4}]}},
            },
        ],
    }
    resp = extract_structured_response("ok", trace, base_chat_req())
    assert resp.entity_type == "Beer"
    assert resp.zeus_data[0]["name"] == "X"