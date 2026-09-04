"""ZCP-77 — correlation header helper (Rewind / Trace-Class)."""

from __future__ import annotations

from zeus_client.adapters.zeus_http.headers import (
    TRACE_CLASS_AGENT,
    TRACE_CLASS_DIRECT_INTERACTIVE,
    TRACE_CLASS_DIRECT_READ,
    TRACE_CLASS_SESSION,
    apply_force_trace_header,
    apply_mode_header,
    correlation_headers,
    rewind_query_params,
    verb_body_without_rewind,
)


def test_correlation_headers_full_agent() -> None:
    h = correlation_headers(
        chat_id="chat-1",
        turn_id="turn-2",
        call_id="call-3",
        mode="analytics",
        force_trace=True,
        trace_class=TRACE_CLASS_AGENT,
    )
    assert h["X-Zeus-Chat-Id"] == "chat-1"
    assert h["X-Zeus-Turn-Id"] == "turn-2"
    assert h["X-Zeus-Call-Id"] == "call-3"
    assert h["X-Zeus-Mode"] == "analytics"
    assert h["X-Zeus-Trace"] == "1"
    assert h["X-Zeus-Trace-Class"] == "agent"
    assert "X-Zeus-Req-Id" not in h
    assert "X-Zeus-Session" not in h
    assert "X-Zeus-Chat-Session-Id" not in h


def test_correlation_headers_chat_session_and_sha12() -> None:
    h = correlation_headers(
        chat_session_id="sess_20260903T120000_000001",
        brief_sha12="3e77b8258d09",
        mini_sha12="5b4692baf06f",
    )
    assert h["X-Zeus-Chat-Session-Id"] == "sess_20260903T120000_000001"
    assert h["X-Zeus-Brief-Sha12"] == "3e77b8258d09"
    assert h["X-Zeus-Mini-Sha12"] == "5b4692baf06f"
    assert "X-Zeus-Session" not in h
    assert "X-Zeus-Req-Id" not in h


def test_correlation_headers_omits_empty() -> None:
    assert correlation_headers() == {}
    assert correlation_headers(chat_id="c") == {"X-Zeus-Chat-Id": "c"}


def test_correlation_headers_closed_classes() -> None:
    assert TRACE_CLASS_AGENT == "agent"
    assert TRACE_CLASS_SESSION == "session"
    assert TRACE_CLASS_DIRECT_INTERACTIVE == "direct.interactive"
    assert TRACE_CLASS_DIRECT_READ == "direct.read"


def test_force_trace_false_does_not_set_header() -> None:
    h = apply_force_trace_header({"X-Zeus-Mode": "analytics"}, False)
    assert "X-Zeus-Trace" not in h


def test_mode_header_does_not_overwrite() -> None:
    h = apply_mode_header({"X-Zeus-Mode": "research"}, "analytics")
    assert h["X-Zeus-Mode"] == "research"


def test_rewind_query_params_off_by_default() -> None:
    assert rewind_query_params(False) == {}
    assert rewind_query_params(True) == {"rewind": "true"}


def test_verb_body_without_rewind_strips_flag() -> None:
    assert verb_body_without_rewind({"entity_type": "Beer", "rewind": True}) == {
        "entity_type": "Beer"
    }
    assert verb_body_without_rewind(None) == {}
