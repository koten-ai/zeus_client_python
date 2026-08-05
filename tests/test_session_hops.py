"""Tests for multi-hop session-trace helpers (Hub Detective E2E)."""
from zeus_client.trace.session_hops import (
    TRACE_SNIPPET_MAX,
    build_aggregate_trace_payload,
    extract_pipeline_meta,
    normalize_hop,
    normalize_hops,
    ordered_req_ids_for_trace_posts,
    select_primary_hop,
    select_primary_req_id,
)


def test_normalize_legacy_tuple():
    hop = normalize_hop(("rid-1", "find", 200, "body", "http://z/find", 12))
    assert hop["req_id"] == "rid-1"
    assert hop["name"] == "find"
    assert hop["status"] == 200
    assert hop["snippet"] == "body"
    assert hop["url"] == "http://z/find"
    assert hop["ms"] == 12


def test_normalize_dict_and_snip_cap():
    long = "x" * (TRACE_SNIPPET_MAX + 50)
    hop = normalize_hop({"req_id": "r", "name": "search", "status": 500, "snippet": long})
    assert len(hop["snippet"]) == TRACE_SNIPPET_MAX


def test_normalize_hops_dedupes_req_id():
    hops = normalize_hops([
        ("a", "find", 200, "", "u1"),
        ("a", "find", 200, "", "u1"),
        ("b", "search", 500, "err", "u2"),
        ("", "x", 200, "", ""),
    ])
    assert [h["req_id"] for h in hops] == ["a", "b"]


def test_select_primary_prefers_error_over_ok_pipeline():
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200, "snippet": "ok", "result_size": 0},
        {"req_id": "s1", "name": "search", "status": 500, "snippet": "timeout"},
    ]
    assert select_primary_req_id(hops) == "s1"


def test_select_primary_prefers_find_with_rows_over_empty_pipeline():
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200, "result_size": 0},
        {"req_id": "f1", "name": "find", "status": 200, "result_size": 5},
    ]
    assert select_primary_req_id(hops) == "f1"


def test_select_primary_prefers_non_pipeline_when_tied():
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200, "snippet": "x"},
        {"req_id": "f1", "name": "find", "status": 200, "snippet": "y"},
    ]
    assert select_primary_req_id(hops) == "f1"


def test_ordered_req_ids_primary_last():
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200},
        {"req_id": "s1", "name": "search", "status": 500},
    ]
    order = ordered_req_ids_for_trace_posts(hops)
    assert order[-1] == "s1"
    assert set(order) == {"p1", "s1"}


def test_build_aggregate_trace_payload_multi_hop():
    hops = [
        {
            "req_id": "p1",
            "name": "pipeline",
            "status": 200,
            "url": "http://z/pipeline",
            "snippet": '{"meta":{}}',
            "ms": 23,
            "step_costs": [
                {"as": "tampa", "status": "ok", "result_size": 0, "ms": 22},
                {"as": "salon_hits", "status": "ok", "result_size": 0, "ms": 2},
            ],
        },
        {
            "req_id": "s1",
            "name": "search",
            "status": 500,
            "url": "http://z/search",
            "snippet": "search_timeout",
            "ms": 2001,
        },
    ]
    primary, turns, zresp, outcome = build_aggregate_trace_payload(hops)
    assert primary == "s1"
    assert outcome == "error"
    assert len(turns) == 2
    assert all(t["role"] == "tool" for t in turns)
    assert "pipeline → 200" in turns[0]["content"]
    assert "result_size=0" in turns[0]["content"]
    assert zresp["aggregate"] is True
    assert zresp["primary_req_id"] == "s1"
    assert zresp["req_ids"] == ["p1", "s1"]
    assert zresp["hop_count"] == 2
    assert len(zresp["tool_hops"]) == 2
    # top-level mirrors primary hop for older UIs
    assert zresp["status"] == 500
    assert zresp["url"] == "http://z/search"
    assert "search_timeout" in zresp["snippet"]


def test_build_aggregate_legacy_tuples():
    primary, turns, zresp, outcome = build_aggregate_trace_payload([
        ("r1", "find", 200, "rows", "http://z/find"),
    ])
    assert primary == "r1"
    assert outcome == "ok"
    assert zresp["req_ids"] == ["r1"]
    assert turns[0]["content"].startswith("find → 200")


def test_extract_pipeline_meta_nested_data():
    body = {
        "status": "ok",
        "data": {
            "meta": {
                "elapsed_ms": 22,
                "steps_executed": 5,
                "step_costs": [
                    {"as": "a", "status": "ok", "result_size": 0},
                    {"as": "b", "status": "ok", "result_size": 3},
                ],
            }
        },
    }
    meta = extract_pipeline_meta(body)
    assert meta["steps_executed"] == 5
    assert meta["result_size"] == 3
    assert len(meta["step_costs"]) == 2
    assert meta.get("pipeline_status") == "ok"


def test_extract_find_result_size():
    body = {"result": {"returned_count": 7, "items": [1, 2]}}
    meta = extract_pipeline_meta(body)
    assert meta["result_size"] == 7


def test_select_primary_hop_empty():
    assert select_primary_hop([]) is None
    assert select_primary_req_id([]) is None
    assert ordered_req_ids_for_trace_posts([]) == []


def test_build_aggregate_empty():
    assert build_aggregate_trace_payload([]) == (None, [], {}, "ok")
    primary, turns, zresp, outcome = build_aggregate_trace_payload(
        [], layer_a={"intent": "List", "confidence": "high"},
    )
    assert primary is None
    assert turns == []
    assert outcome == "ok"
    assert zresp["layer_a"]["intent"] == "List"


def test_build_aggregate_includes_layer_a():
    hops = [{"req_id": "r1", "name": "pipeline", "status": 200, "snippet": "ok"}]
    la = {
        "intent": "List",
        "query_decomposition": {"intent": "List", "entity": "Business"},
        "decomposition": {"targets": ["Business"]},
        "confidence": "high",
        "summary": "found 3",
    }
    primary, turns, zresp, outcome = build_aggregate_trace_payload(hops, layer_a=la)
    assert primary == "r1"
    assert outcome == "ok"
    assert zresp["layer_a"]["intent"] == "List"
    assert zresp["layer_a"]["query_decomposition"]["entity"] == "Business"
