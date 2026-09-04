"""Multi-hop session-trace projector oracles (ZCP-15 · Task 5.2).

Port of tests/test_session_hops.py — pure ranking/aggregate + soft-fail posts.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from tests.fixtures.catalog_brief import BRIEF

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.session import HttpxSessionClient
from zeus_client.application.detective.extract import catalog_flags_of, sha12, slice_block
from zeus_client.application.projectors.session_trace import (
    TRACE_SNIPPET_MAX,
    AggregateTracePayload,
    build_aggregate_trace_payload,
    extract_pipeline_meta,
    normalize_hop,
    normalize_hops,
    ordered_req_ids_for_trace_posts,
    project_session_trace,
    select_primary_hop,
    select_primary_req_id,
)
from zeus_client.config.models import ZeusEndpointConfig
from zeus_client.domain.session import SessionHandle


def test_aggregate_includes_product_stamp() -> None:
    agg = build_aggregate_trace_payload(
        [{"req_id": "r1", "name": "find", "status": 200}],
        stamp={"user": "zeus_client", "version": "2.1.0"},
    )
    assert agg.zeus_response["user"] == "zeus_client"
    assert agg.zeus_response["version"] == "2.1.0"


def test_normalize_legacy_tuple() -> None:
    hop = normalize_hop(("rid-1", "find", 200, "body", "http://z/find", 12))
    assert hop["req_id"] == "rid-1"
    assert hop["name"] == "find"
    assert hop["status"] == 200
    assert hop["snippet"] == "body"
    assert hop["url"] == "http://z/find"
    assert hop["ms"] == 12


def test_normalize_dict_and_snip_cap() -> None:
    long = "x" * (TRACE_SNIPPET_MAX + 50)
    hop = normalize_hop({"req_id": "r", "name": "search", "status": 500, "snippet": long})
    assert len(hop["snippet"]) == TRACE_SNIPPET_MAX


def test_normalize_hops_dedupes_req_id() -> None:
    hops = normalize_hops(
        [
            ("a", "find", 200, "", "u1"),
            ("a", "find", 200, "", "u1"),
            ("b", "search", 500, "err", "u2"),
            ("", "x", 200, "", ""),
        ]
    )
    assert [h["req_id"] for h in hops] == ["a", "b"]


def test_select_primary_prefers_error_over_ok_pipeline() -> None:
    hops = [
        {
            "req_id": "p1",
            "name": "pipeline",
            "status": 200,
            "snippet": "ok",
            "result_size": 0,
        },
        {"req_id": "s1", "name": "search", "status": 500, "snippet": "timeout"},
    ]
    assert select_primary_req_id(hops) == "s1"


def test_select_primary_prefers_find_with_rows_over_empty_pipeline() -> None:
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200, "result_size": 0},
        {"req_id": "f1", "name": "find", "status": 200, "result_size": 5},
    ]
    assert select_primary_req_id(hops) == "f1"


def test_select_primary_prefers_non_pipeline_when_tied() -> None:
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200, "snippet": "x"},
        {"req_id": "f1", "name": "find", "status": 200, "snippet": "y"},
    ]
    assert select_primary_req_id(hops) == "f1"


def test_ordered_req_ids_primary_last() -> None:
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200},
        {"req_id": "s1", "name": "search", "status": 500},
    ]
    order = ordered_req_ids_for_trace_posts(hops)
    assert order[-1] == "s1"
    assert set(order) == {"p1", "s1"}


def test_build_aggregate_trace_payload_multi_hop() -> None:
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
    agg = build_aggregate_trace_payload(hops)
    assert isinstance(agg, AggregateTracePayload)
    assert agg.primary_req_id == "s1"
    assert agg.outcome == "error"
    assert len(agg.turns) == 2
    assert all(t["role"] == "tool" for t in agg.turns)
    assert "pipeline → 200" in agg.turns[0]["content"]
    assert "result_size=0" in agg.turns[0]["content"]
    zresp = agg.zeus_response
    assert zresp["aggregate"] is True
    assert zresp["primary_req_id"] == "s1"
    assert zresp["req_ids"] == ["p1", "s1"]
    assert zresp["hop_count"] == 2
    assert len(zresp["tool_hops"]) == 2
    assert zresp["status"] == 500
    assert zresp["url"] == "http://z/search"
    assert "search_timeout" in zresp["snippet"]


def test_build_aggregate_legacy_tuples() -> None:
    agg = build_aggregate_trace_payload([("r1", "find", 200, "rows", "http://z/find")])
    assert agg.primary_req_id == "r1"
    assert agg.outcome == "ok"
    assert agg.zeus_response["req_ids"] == ["r1"]
    assert agg.turns[0]["content"].startswith("find → 200")


def test_extract_pipeline_meta_nested_data() -> None:
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


def test_extract_find_result_size() -> None:
    body = {"result": {"returned_count": 7, "items": [1, 2]}}
    meta = extract_pipeline_meta(body)
    assert meta["result_size"] == 7


def test_select_primary_hop_empty() -> None:
    assert select_primary_hop([]) is None
    assert select_primary_req_id([]) is None
    assert ordered_req_ids_for_trace_posts([]) == []


def test_build_aggregate_empty() -> None:
    agg = build_aggregate_trace_payload([])
    assert agg.primary_req_id is None
    assert agg.turns == ()
    assert agg.zeus_response == {}
    assert agg.outcome == "ok"
    agg2 = build_aggregate_trace_payload([], layer_a={"intent": "List", "confidence": "high"})
    assert agg2.primary_req_id is None
    assert agg2.turns == ()
    assert agg2.outcome == "ok"
    assert agg2.zeus_response["layer_a"]["intent"] == "List"


def test_build_aggregate_includes_tokens_and_omits_when_absent() -> None:
    hops = [{"req_id": "r1", "name": "find", "status": 200, "snippet": "ok"}]
    bag = {
        "prompt": 30,
        "completion": 3,
        "total": 33,
        "rounds": 2,
        "ok": True,
    }
    with_tok = build_aggregate_trace_payload(hops, tokens=bag)
    assert with_tok.zeus_response["tokens"]["prompt"] == 30
    assert with_tok.zeus_response["tokens"]["rounds"] == 2
    without = build_aggregate_trace_payload(hops)
    assert "tokens" not in without.zeus_response
    empty = build_aggregate_trace_payload([], tokens=bag)
    assert empty.zeus_response["tokens"]["prompt"] == 30


def test_build_aggregate_includes_layer_a() -> None:
    hops = [{"req_id": "r1", "name": "pipeline", "status": 200, "snippet": "ok"}]
    la = {
        "intent": "List",
        "query_decomposition": {"intent": "List", "entity": "Business"},
        "decomposition": {"targets": ["Business"]},
        "confidence": "high",
        "summary": "found 3",
    }
    agg = build_aggregate_trace_payload(hops, layer_a=la)
    assert agg.primary_req_id == "r1"
    assert agg.outcome == "ok"
    assert agg.zeus_response["layer_a"]["intent"] == "List"
    assert agg.zeus_response["layer_a"]["query_decomposition"]["entity"] == "Business"


def test_build_aggregate_inject_brief_sha12_matches_catalog_slice() -> None:
    system = "LOCKED RULES (hashed)\n\n" + BRIEF
    hops = [{"req_id": "r1", "name": "find", "status": 200, "snippet": "ok"}]
    flags = catalog_flags_of(system=system)
    inj = {
        "has_scope_brief": flags["has_scope_brief"],
        "has_mini_schema": flags["has_mini_schema"],
        "brief_sha12": flags["brief_sha12"],
        "mini_sha12": flags["mini_sha12"],
    }
    agg = build_aggregate_trace_payload(hops, inject=inj)
    brief = slice_block(system, "brief")
    mini = slice_block(system, "mini")
    zinj = agg.zeus_response["inject"]
    assert zinj["brief_sha12"] == sha12(brief)
    assert zinj["mini_sha12"] == sha12(mini)
    assert zinj["brief_sha12"] != sha12(system)
    assert zinj["has_scope_brief"] is True
    assert zinj["has_mini_schema"] is True
    assert "system_message" not in zinj
    assert "brief_preview" not in zinj
    assert "mini_preview" not in zinj


def test_build_aggregate_empty_still_stamps_inject() -> None:
    system = "LOCKED\n\n" + BRIEF
    flags = catalog_flags_of(system=system)
    inj = {
        "has_scope_brief": flags["has_scope_brief"],
        "has_mini_schema": flags["has_mini_schema"],
        "brief_sha12": flags["brief_sha12"],
        "mini_sha12": flags["mini_sha12"],
    }
    agg = build_aggregate_trace_payload([], inject=inj)
    assert agg.zeus_response["inject"]["brief_sha12"] == sha12(slice_block(system, "brief"))


@pytest.mark.asyncio
@respx.mock
async def test_project_session_trace_posts_identical_body_primary_last() -> None:
    """Secondaries first, primary last; identical aggregate body each post."""
    ZEUS = "http://zeus.test:8080"
    posts: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        posts.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"contract_status": "match"},
            headers={"X-Zeus-Req-Id": "trace-post"},
        )

    respx.post(f"{ZEUS}/v2/session/trace").mock(side_effect=_capture)
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    handle = SessionHandle(
        session_id="sid-1",
        round=2,
        chat_id="c",
        contract_id="cid",
        contract_hash="md5:h",
        contract_status="match",
        enabled=True,
    )
    hops = [
        {"req_id": "p1", "name": "pipeline", "status": 200, "snippet": "ok"},
        {"req_id": "s1", "name": "search", "status": 500, "snippet": "boom"},
    ]
    result = await project_session_trace(
        http,
        handle=handle,
        hops=hops,
        chat_request={"messages": []},
        inject={"has_scope_brief": True, "brief_sha12": "slicehash12"},
        mode="analytics",
        turn_id="turn-agg-1",
    )
    assert result.ok
    assert result.primary_req_id == "s1"
    assert result.post_order == ("p1", "s1")
    assert len(posts) == 2
    assert [p["req_id"] for p in posts] == ["p1", "s1"]
    # Identical multi-hop body (except req_id join key)
    for p in posts:
        assert p["session_id"] == "sid-1"
        assert p["turn_id"] == "turn-agg-1"
        assert p["round"] == 2
        assert p["zeus_response"]["aggregate"] is True
        assert p["zeus_response"]["primary_req_id"] == "s1"
        assert p["zeus_response"]["req_ids"] == ["p1", "s1"]
        assert p["zeus_response"]["inject"]["brief_sha12"] == "slicehash12"
        assert p["outcome"] == "error"
        assert len(p["turns"]) == 2
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_project_session_trace_soft_fail_on_http_error() -> None:
    ZEUS = "http://zeus.test:8080"
    respx.post(f"{ZEUS}/v2/session/trace").mock(return_value=httpx.Response(500, text="fail"))
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    handle = SessionHandle(
        session_id="sid-1",
        round=1,
        enabled=True,
        contract_id="c",
        contract_hash="h",
    )
    result = await project_session_trace(
        http,
        handle=handle,
        hops=[{"req_id": "r1", "name": "find", "status": 200}],
        chat_request={},
    )
    # Soft-fail: does not raise; reports failures
    assert result.ok is False
    assert result.errors
    assert result.primary_req_id == "r1"
    await http.aclose()


@pytest.mark.asyncio
async def test_project_session_trace_noop_when_disabled_or_no_hops() -> None:
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url="http://zeus.test:8080"),
        secrets=EnvSecretStore({}),
    )
    disabled = SessionHandle(session_id="s", round=1, enabled=False)
    r1 = await project_session_trace(http, handle=disabled, hops=[{"req_id": "a"}])
    assert r1.ok is True
    assert r1.posts == 0

    enabled = SessionHandle(session_id="s", round=1, enabled=True)
    r2 = await project_session_trace(http, handle=enabled, hops=[])
    assert r2.ok is True
    assert r2.posts == 0
    await http.aclose()
