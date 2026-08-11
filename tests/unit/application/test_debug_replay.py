"""Debug export + transport replay (ZCP-20)."""

from __future__ import annotations

import pytest

from zeus_client_v2.application.debug_export import (
    build_span_tree,
    event_type_sequence,
    export_journal_redacted,
    mermaid_timeline,
)
from zeus_client_v2.application.replay import (
    ReplayMode,
    assert_event_type_sequence,
    transport_replay,
)
from zeus_client_v2.config.models import RuntimeConfig
from zeus_client_v2.domain.journal import InMemoryJournal, JournalEvent, SpanTracer
from zeus_client_v2.domain.journal.events import (
    EVENT_LLM_ROUND,
    EVENT_NOTE,
    EVENT_SPAN_ENDED,
    EVENT_SPAN_STARTED,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_ZEUS_HOP,
)
from zeus_client_v2.runtime import ZeusRuntime


def _fill_turn(j: InMemoryJournal, turn_id: str = "turn_a") -> None:
    j.append(
        JournalEvent(
            event_id="e1",
            ts_ms=1,
            type=EVENT_TURN_STARTED,
            component="test",
            turn_id=turn_id,
            span_id=None,
            parent_span_id=None,
            data={"msg": "start"},
        )
    )
    tr = SpanTracer(journal=j, turn_id=turn_id, _clock_ms=lambda: 10)
    h = tr.start("agent.round")
    j.append(
        JournalEvent(
            event_id="e2",
            ts_ms=11,
            type=EVENT_LLM_ROUND,
            component="test",
            turn_id=turn_id,
            span_id=h.span_id,
            parent_span_id=None,
            data={"ok": True, "Authorization": "Bearer sk-secret-key-value"},
        )
    )
    j.append(
        JournalEvent(
            event_id="e3",
            ts_ms=12,
            type=EVENT_ZEUS_HOP,
            component="test",
            turn_id=turn_id,
            span_id=h.span_id,
            parent_span_id=None,
            data={"req_id": "req-1", "api_key": "should-redact"},
        )
    )
    tr.end(h, status="ok")
    j.append(
        JournalEvent(
            event_id="e4",
            ts_ms=20,
            type=EVENT_TURN_COMPLETED,
            component="test",
            turn_id=turn_id,
            span_id=None,
            parent_span_id=None,
            data={"status": "ok"},
        )
    )


def test_export_redacts_sensitive_keys():
    j = InMemoryJournal()
    _fill_turn(j)
    exp = export_journal_redacted(j)
    d = exp.to_dict()
    assert d["journal_schema"] == 1
    blob = str(d)
    assert "sk-secret-key-value" not in blob
    assert "should-redact" not in blob
    # redacted markers present
    assert "[REDACTED]" in blob or "REDACTED" in blob
    types = event_type_sequence(exp)
    assert types[0] == EVENT_TURN_STARTED
    assert EVENT_LLM_ROUND in types
    assert EVENT_ZEUS_HOP in types
    assert types[-1] == EVENT_TURN_COMPLETED


def test_span_tree_parent_linkage():
    j = InMemoryJournal()
    tr = SpanTracer(journal=j, turn_id="t1", _clock_ms=lambda: 1)
    root = tr.start("root")
    child = tr.start("child", parent_span_id=root.span_id)
    tr.end(child)
    tr.end(root)
    tree = build_span_tree(j, turn_id="t1")
    assert len(tree.roots) == 1
    assert tree.roots[0].name == "root"
    assert len(tree.roots[0].children) == 1
    assert tree.roots[0].children[0].name == "child"
    mm = mermaid_timeline(j, turn_id="t1")
    assert "flowchart" in mm
    assert "root" in mm


def test_transport_replay_greentest_exact():
    j = InMemoryJournal()
    _fill_turn(j, "turn_a")
    expected = (
        EVENT_TURN_STARTED,
        EVENT_SPAN_STARTED,
        EVENT_LLM_ROUND,
        EVENT_ZEUS_HOP,
        EVENT_SPAN_ENDED,
        EVENT_TURN_COMPLETED,
    )
    r = transport_replay(j, expected_types=expected, turn_id="turn_a")
    assert r.ok is True
    assert r.mode is ReplayMode.TRANSPORT
    assert r.actual_types == expected


def test_transport_replay_mismatch():
    j = InMemoryJournal()
    _fill_turn(j)
    r = transport_replay(
        j,
        expected_types=(EVENT_TURN_STARTED, EVENT_NOTE),
        turn_id="turn_a",
    )
    assert r.ok is False
    assert r.errors


def test_transport_replay_subsequence_allow_extra():
    j = InMemoryJournal()
    _fill_turn(j)
    r = transport_replay(
        j,
        expected_types=(EVENT_TURN_STARTED, EVENT_LLM_ROUND, EVENT_TURN_COMPLETED),
        allow_extra=True,
        turn_id="turn_a",
    )
    assert r.ok is True


def test_assert_event_type_sequence_helpers():
    assert assert_event_type_sequence(["a", "b"], ["a", "b"]) == []
    assert assert_event_type_sequence(["a", "x", "b"], ["a", "b"], allow_extra=True) == []
    assert assert_event_type_sequence(["a"], ["a", "b"]) != []


@pytest.mark.asyncio
async def test_runtime_debug_api():
    j = InMemoryJournal()
    _fill_turn(j, "turn_rt")
    async with ZeusRuntime(RuntimeConfig(), journal=j) as rt:
        exp = rt.debug.export_journal(turn_id="turn_rt")
        assert exp.journal_schema == 1
        assert event_type_sequence(exp)[0] == EVENT_TURN_STARTED
        tree = rt.debug.spans(turn_id="turn_rt")
        assert tree.roots
        r = await rt.debug.replay(
            expected_types=(
                EVENT_TURN_STARTED,
                EVENT_SPAN_STARTED,
                EVENT_LLM_ROUND,
                EVENT_ZEUS_HOP,
                EVENT_SPAN_ENDED,
                EVENT_TURN_COMPLETED,
            ),
            turn_id="turn_rt",
        )
        assert r.ok is True
        r2 = await rt.debug.replay(mode="agent")
        assert r2.ok is False
        assert "not implemented" in r2.errors[0]
