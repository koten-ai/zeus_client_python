"""Hub join catalog + terminate bags (ZCP-117)."""

from __future__ import annotations

from zeus_client.application.detective.extract import (
    catalog_for_session_trace,
    terminate_for_session_trace,
)


def _fn(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


_THIRTEEN = [
    "describe",
    "get",
    "find",
    "search",
    "pipeline",
    "return",
    "project",
    "aggregate",
    "traverse",
    "hybrid_search",
    "fts_search",
    "explain",
    "count",
]


def test_catalog_for_session_trace_13_tools() -> None:
    tools = [_fn(n) for n in _THIRTEEN]
    bag = catalog_for_session_trace(
        tools=tools,
        chat_request={"_lineage": {"base_id": "base-6.1", "custom_id": None}},
        contract_id="travel_analytics_v1",
        contract_hash="md5:abc",
        scope="travel-sample/inventory",
    )
    assert bag["tool_count"] == 13
    assert bag["tool_names"] == _THIRTEEN
    assert bag["has_return_verb"] is True
    assert bag["has_pipeline_verb"] is True
    assert bag["base_id"] == "base-6.1"
    assert bag["custom_label"] == "custom {travel-sample/inventory}"
    assert bag["contract_id"] == "travel_analytics_v1"
    assert bag["contract_hash"] == "md5:abc"


def test_catalog_does_not_invent_pipeline_or_return() -> None:
    bag = catalog_for_session_trace(tools=[_fn("find"), _fn("search")])
    assert bag["has_return_verb"] is False
    assert bag["has_pipeline_verb"] is False
    assert bag["tool_count"] == 2


def test_catalog_unique_preserves_order() -> None:
    bag = catalog_for_session_trace(tools=[_fn("find"), _fn("find"), _fn("return")])
    assert bag["tool_names"] == ["find", "return"]
    assert bag["tool_count"] == 2


def test_terminate_return_and_cheap_final() -> None:
    ret = terminate_for_session_trace(
        terminate_via="return",
        ai_process_result=True,
        layer_parsed=True,
    )
    assert ret["has_terminate"] is True
    assert ret["terminate_via"] == "return"
    assert ret["cheap_final"] is False
    assert ret["ai_process_result"] is True

    cheap = terminate_for_session_trace(
        terminate_via="client_terminate",
        exit_kind="cheap_final",
        ai_process_result=False,
        layer_parsed=False,
    )
    assert cheap["cheap_final"] is True
    assert cheap["terminate_via"] == "cheap_final"
    assert cheap["has_terminate"] is True


def test_terminate_omits_has_when_no_bag() -> None:
    bag = terminate_for_session_trace(
        terminate_via="client_terminate",
        exit_kind="direct",
        layer_parsed=False,
    )
    assert bag["has_terminate"] is False
    assert bag["terminate_via"] == "client_terminate"
