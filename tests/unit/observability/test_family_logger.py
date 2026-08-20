"""Family logger levels + REDACT (CHECKLIST D / LOGGING.md)."""

from __future__ import annotations

import logging

from zeus_client.observability.logging import (
    CaptureLogHandler,
    FamilyLogger,
    configure_family_logger,
    redact_attrs,
)


def _capture_logger(level: int = logging.DEBUG) -> tuple[list[dict], FamilyLogger]:
    sink: list[dict] = []
    lg = logging.getLogger("zeus_client.test_family")
    lg.handlers.clear()
    lg.addHandler(CaptureLogHandler(sink))
    lg.setLevel(level)
    lg.propagate = False
    fl = FamilyLogger(level="trace", redact=True, logger=lg, service_name="zeus_client")
    return sink, fl


def test_info_event_name_and_attrs() -> None:
    sink, fl = _capture_logger()
    fl.info("zeus_client.turn.started", **{"session.id": "sess_1", "scope": "b/s"})
    rec = next(r for r in sink if r["event"] == "zeus_client.turn.started")
    assert rec["level"] == "INFO"
    assert rec["attrs"]["session.id"] == "sess_1"


def test_hard_deny_secret_when_redact_false() -> None:
    attrs = redact_attrs(
        {"authorization": "Bearer sk-secret", "req_id": "abc"},
        redact=False,
    )
    assert attrs["authorization"] == "[REDACTED]"
    assert attrs["req_id"] == "abc"


def test_trace_level_below_debug() -> None:
    sink, fl = _capture_logger(level=logging.DEBUG)
    fl.set_level("debug")
    fl.trace("zeus_client.tool.result_shape", verb="find", bytes=12)
    assert not any(r["event"] == "zeus_client.tool.result_shape" for r in sink)
    fl.set_level("trace")
    fl.trace("zeus_client.tool.result_shape", verb="find")
    assert any(r["event"] == "zeus_client.tool.result_shape" for r in sink)


def test_configure_redact_false_is_loud() -> None:
    sink: list[dict] = []
    lg = logging.getLogger("zeus_client")
    handler = CaptureLogHandler(sink)
    lg.addHandler(handler)
    try:
        configure_family_logger(level="info", redact=False)
        assert any(
            r["event"] == "zeus_client.logging.configured" and r["attrs"].get("redact") is False
            for r in sink
        )
    finally:
        lg.removeHandler(handler)
        configure_family_logger(level="info", redact=True)
