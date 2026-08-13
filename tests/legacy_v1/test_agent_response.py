"""Tests for structured zeus_data extraction from agent traces."""

import copy

from tests.fixtures.catalog_brief import base_chat_req
from zeus_client.agent.response import (
    StructuredAgentResponse,
    extract_structured_response,
    filter_rows_to_schema,
    resolve_field_allowlist,
)


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


def test_terminating_pipeline_named_step_binding_under_data():
    """V2 terminating pipeline returns data.<as>.rows plus meta keys — not a flat list.

    Regression: treating the whole data dict as one Business/Beer row dropped
    step bindings (tampa_proj/vaProj) as unknown fields → empty zeus_data.
    """
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "pipeline",
                "status": 200,
                "args": {
                    "steps": [
                        {
                            "as": "cands",
                            "verb": "find",
                            "entity_type": "Beer",
                            "where": {"city": "Arena"},
                            "return": "ids",
                        },
                        {
                            "as": "vaProj",
                            "verb": "project",
                            "ids": "@cands.ids",
                            "fields": ["name", "abv"],
                            "format": "row",
                        },
                    ],
                    "return": ["vaProj"],
                    "summary": "Beers in Arena",
                    "confidence": "high",
                    "decomposition": {"targets": ["Beer"], "predicates": {"city": "Arena"}},
                },
                "result_json": {
                    "confidence": "high",
                    "data": {
                        "job_fingerprint": {
                            "algorithm": "md5",
                            "canonical_bytes": 590,
                            "server_md5": "md5:deadbeef",
                            "verified": False,
                        },
                        "meta": {"elapsed_ms": 18, "steps_executed": 2, "total_cost": 3.05},
                        "status": "ok",
                        "vaProj": {
                            "rows": [
                                {
                                    "id": "file::abc",
                                    "doc_key": "beer:1",
                                    "name": "Coopers Sparkling Ale",
                                    "abv": 5.8,
                                    "node_id": "file::abc",
                                },
                                {
                                    "id": "file::def",
                                    "doc_key": "beer:2",
                                    "name": "Pale Lager",
                                    "abv": 4.2,
                                    "node_id": "file::def",
                                },
                            ]
                        },
                    },
                    "decomposition": {"targets": ["Beer"], "predicates": {"city": "Arena"}},
                    "summary": "Beers in Arena",
                    "turn_complete": True,
                },
            },
        ],
    }
    resp = extract_structured_response("Beers in Arena", trace, base_chat_req())
    assert resp.source_tool == "pipeline"
    assert resp.entity_type == "Beer"
    assert len(resp.zeus_data) == 2
    assert resp.zeus_data[0]["name"] == "Coopers Sparkling Ale"
    assert resp.zeus_data[0]["abv"] == 5.8
    assert resp.zeus_data[0]["id"] == "file::abc"
    assert resp.zeus_data[1]["name"] == "Pale Lager"
    # Envelope keys must not surface as dropped "fields on entity Beer"
    assert not any("job_fingerprint" in w for w in resp.warnings)
    assert not any("tampa_proj" in w or "vaProj" in w for w in resp.warnings)
    assert not any("dropped unknown field 'meta'" in w for w in resp.warnings)
    assert not any("dropped unknown field 'status'" in w for w in resp.warnings)


def test_terminating_pipeline_prefers_return_binding_order():
    """When multiple step bindings have rows, use pipeline return[] order."""
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "pipeline",
                "status": 200,
                "args": {
                    "steps": [
                        {"as": "first", "verb": "find", "entity_type": "Beer"},
                        {"as": "second", "verb": "project", "entity_type": "Beer"},
                    ],
                    "return": ["second"],
                },
                "result_json": {
                    "data": {
                        "status": "ok",
                        "first": {
                            "rows": [{"id": "n_old", "name": "Skip Me", "abv": 1.0}],
                        },
                        "second": {
                            "rows": [{"id": "n_keep", "name": "Keep Me", "abv": 6.0}],
                        },
                    },
                },
            },
        ],
    }
    resp = extract_structured_response("ok", trace, base_chat_req())
    assert len(resp.zeus_data) == 1
    assert resp.zeus_data[0]["name"] == "Keep Me"
    assert resp.zeus_data[0]["id"] == "n_keep"


def test_terminating_pipeline_items_under_named_binding():
    """Some verbs emit items instead of rows under the step binding."""
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "pipeline",
                "status": 200,
                "args": {
                    "steps": [{"as": "hits", "verb": "find", "entity_type": "Beer"}],
                    "return": ["hits"],
                },
                "result_json": {
                    "data": {
                        "status": "ok",
                        "hits": {
                            "items": [{"id": "n_1", "name": "IPA", "abv": 6.5}],
                        },
                    },
                },
            },
        ],
    }
    resp = extract_structured_response("ok", trace, base_chat_req())
    assert resp.zeus_data == [{"id": "n_1", "name": "IPA", "abv": 6.5}]


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


def test_get_inherits_entity_type_from_prior_find():
    """find then get is the common hydrate pattern; get args have no entity_type."""
    trace = {
        "steps": [{"type": "return", "args": {"summary": "hydrated beers"}}],
        "tool_calls": [
            {
                "name": "find",
                "status": 200,
                "args": {"entity_type": "Beer", "return": "rows"},
                "result_json": {
                    "result": {
                        "items": [
                            {"id": "n_1", "name": "IPA"},
                            {"id": "n_2", "name": "Stout"},
                        ]
                    }
                },
            },
            {
                "name": "get",
                "status": 200,
                "args": {"ids": ["n_1", "n_2"], "include": ["name", "abv"]},
                "result_json": {
                    "result": {
                        "items": [
                            {"id": "n_1", "name": "IPA", "abv": 6.5, "secret": "x"},
                            {"id": "n_2", "name": "Stout", "abv": 5.0},
                        ]
                    }
                },
            },
        ],
    }
    resp = extract_structured_response("hydrated beers", trace, base_chat_req())
    assert resp.source_tool == "get"
    assert resp.entity_type == "Beer"
    assert len(resp.zeus_data) == 2
    assert resp.zeus_data[0] == {"id": "n_1", "name": "IPA", "abv": 6.5}
    assert "secret" not in resp.zeus_data[0]
    assert not any("entity_type unknown" in w for w in resp.warnings)


def test_entity_type_from_row_field_when_get_has_no_prior_tool():
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "get",
                "status": 200,
                "args": {"ids": ["n_1"]},
                "result_json": {
                    "result": {
                        "items": [
                            {
                                "id": "n_1",
                                "entity_type": "Beer",
                                "name": "Porter",
                                "abv": 5.5,
                                "noise": 1,
                            }
                        ]
                    }
                },
            },
        ],
    }
    resp = extract_structured_response("porter", trace, base_chat_req())
    assert resp.source_tool == "get"
    assert resp.entity_type == "Beer"
    assert resp.zeus_data == [{"id": "n_1", "entity_type": "Beer", "name": "Porter", "abv": 5.5}]
    assert not any("entity_type unknown" in w for w in resp.warnings)


def test_multi_entity_output_schema_uses_inferred_entity_type():
    """Demo-style multi-key output_schema must not require a single default entity."""
    override = {
        "Hotel": ["id", "name", "city"],
        "Beer": ["id", "name", "abv"],
        "Airport": ["id", "name", "faa"],
    }
    trace = {
        "steps": [],
        "tool_calls": [
            {
                "name": "find",
                "status": 200,
                "args": {"entity_type": "Hotel"},
                "result_json": {
                    "result": {"items": [{"id": "h1", "name": "Plaza", "city": "Paris"}]}
                },
            },
            {
                "name": "get",
                "status": 200,
                "args": {"ids": ["h1"], "include": ["name", "city"]},
                "result_json": {
                    "result": {
                        "items": [
                            {
                                "id": "h1",
                                "name": "Plaza",
                                "city": "Paris",
                                "hotel_details": {"rooms": 10},
                            }
                        ]
                    }
                },
            },
        ],
    }
    resp = extract_structured_response(
        "hotels",
        trace,
        base_chat_req(),
        output_schema=override,
    )
    assert resp.entity_type == "Hotel"
    assert resp.zeus_data == [{"id": "h1", "name": "Plaza", "city": "Paris"}]
    assert any("hotel_details" in w for w in resp.warnings)
