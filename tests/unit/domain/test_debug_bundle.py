"""DebugBundle gather surface (ZCP-86)."""

from __future__ import annotations

from zeus_client.domain.messages import DebugBundle


def test_debug_bundle_to_dict_includes_nine_gather_keys() -> None:
    b = DebugBundle(
        turn_id="turn_abc",
        chat_id="chat_1",
        session_id="sess_1",
        preferred_req_id="req-a",
        req_ids=("req-a", "req-b"),
        zeus_url="http://127.0.0.1:8080",
        client_version="2.0.0",
        target={
            "bucket": "yelp-data",
            "scope": "_default",
            "collection": "_default",
            "mode": "analytics",
        },
        catalog={"has_scope_brief": True, "has_mini_schema": True, "tools_count": 13},
        contract_status="match",
        tokens={
            "prompt": 10,
            "completion": 4,
            "total": 14,
            "cached": 0,
            "extra": 0,
            "ok": True,
        },
        export_ref="turn_abc",
        stamp={"user": "zeus_client", "version": "2.1.0"},
        trace_id="abc",
    )
    d = b.to_dict()
    assert d["turn_id"] == "turn_abc"
    assert d["chat_id"] == "chat_1"
    assert d["session_id"] == "sess_1"
    assert d["req_ids"] == ["req-a", "req-b"]
    assert d["preferred_req_id"] == "req-a"
    assert d["zeus_url"].endswith(":8080")
    assert d["client_version"]
    assert d["target"]["bucket"] == "yelp-data"
    assert d["catalog"]["tools_count"] == 13
    assert d["contract_status"] == "match"
    assert d["tokens"]["ok"] is True
    assert d["export_ref"] == "turn_abc"
    assert d["stamp"]["user"] == "zeus_client"
    assert d["trace_id"] == "abc"
    assert "answer" not in d


def test_debug_bundle_defaults_still_construct() -> None:
    b = DebugBundle(rounds=1)
    assert b.req_ids == ()
    assert b.export_ref is None
    assert b.to_dict()["journal_schema"] == 1
