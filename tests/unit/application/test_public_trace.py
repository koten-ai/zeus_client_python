"""public_trace session block (ZCP-97)."""

from __future__ import annotations

from zeus_client.application.projectors.public_trace import build_public_trace


def test_public_trace_includes_session_when_ids_present() -> None:
    pt = build_public_trace(
        turn_id="turn_1",
        answer="ok",
        status="ok",
        rounds=1,
        notes=(),
        hops=({"req_id": "req-a", "name": "find"},),
        ai_process_result=True,
        ai_process_result_exit="direct",
        layer_a=None,
        policy=None,
        flags={},
        session={
            "id": "sess_1",
            "req_ids": ["req-a"],
            "preferred_req_id": "req-a",
            "contract_status": "match",
        },
    )
    assert pt["session"]["id"] == "sess_1"
    assert pt["session"]["req_ids"] == ["req-a"]


def test_public_trace_omits_session_when_empty() -> None:
    pt = build_public_trace(
        turn_id="turn_1",
        answer="ok",
        status="ok",
        rounds=1,
        notes=(),
        hops=(),
        ai_process_result=True,
        ai_process_result_exit="direct",
        layer_a=None,
        policy=None,
        flags={},
    )
    assert "session" not in pt
