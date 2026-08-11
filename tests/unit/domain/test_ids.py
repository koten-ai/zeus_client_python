"""Unit tests for V2 typed domain IDs (ZCP-4 / Task 1.1)."""

from __future__ import annotations

import pytest

from zeus_client_v2.domain.ids import CallId, ChatId, ReqId, SessionId, TurnId, new_id


def test_turn_id_is_str_subclass_and_distinct_type() -> None:
    t = TurnId("turn_abc")
    assert isinstance(t, str)
    assert t == "turn_abc"
    assert type(t) is TurnId


def test_all_id_wrappers_round_trip_str() -> None:
    cases = [
        (TurnId, "t1"),
        (ChatId, "c1"),
        (CallId, "call1"),
        (SessionId, "sid1"),
        (ReqId, "req1"),
    ]
    for cls, raw in cases:
        wrapped = cls(raw)
        assert str(wrapped) == raw
        assert wrapped == raw  # compares equal to bare str
        assert type(wrapped) is cls


def test_new_id_prefix_and_nonempty() -> None:
    tid = new_id(TurnId, prefix="turn_")
    assert isinstance(tid, TurnId)
    assert tid.startswith("turn_")
    assert len(tid) > len("turn_")


def test_id_wrappers_reject_empty() -> None:
    with pytest.raises(ValueError):
        TurnId("")
    with pytest.raises(ValueError):
        ReqId("   ")
