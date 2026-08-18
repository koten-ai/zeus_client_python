"""Journal unit tests — append order, payload dedup, export schema, spans (ZCP-6)."""

from __future__ import annotations

from zeus_client.domain.journal import (
    JOURNAL_SCHEMA_VERSION,
    InMemoryJournal,
    JournalEvent,
    SpanTracer,
)
from zeus_client.domain.journal.events import (
    EVENT_JOB_FINISHED,
    EVENT_JOB_STARTED,
    EVENT_NOTE,
    EVENT_SPAN_ENDED,
    EVENT_SPAN_STARTED,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    EVENT_UNIT_FINISHED,
    EVENT_UNIT_STARTED,
)
from zeus_client.domain.journal.payload_store import InMemoryPayloadStore


def _evt(event_id: str, ts: int, typ: str = EVENT_NOTE, **kwargs: object) -> JournalEvent:
    base = dict(
        event_id=event_id,
        ts_ms=ts,
        type=typ,
        component="test",
        turn_id="turn_1",
        span_id=None,
        parent_span_id=None,
        data={"n": event_id},
    )
    base.update(kwargs)
    return JournalEvent(**base)  # type: ignore[arg-type]


def test_journal_append_order() -> None:
    j = InMemoryJournal()
    j.append(_evt("e1", 10, EVENT_TURN_STARTED))
    j.append(_evt("e2", 20, EVENT_NOTE))
    j.append(_evt("e3", 30, EVENT_TURN_COMPLETED))
    ids = [e.event_id for e in j.events()]
    assert ids == ["e1", "e2", "e3"]
    # immutability of returned sequence
    evs = j.events()
    assert isinstance(evs, tuple)


def test_payload_ref_dedup() -> None:
    store = InMemoryPayloadStore()
    body = b'{"hello":"world"}'
    r1 = store.put(body, content_type="application/json", kind="http_body")
    r2 = store.put(body, content_type="application/json", kind="http_body")
    assert r1 == r2
    assert r1.startswith("sha256:")
    assert store.get(r1) == body
    other = store.put(b"other", content_type="text/plain", kind="note")
    assert other != r1


def test_export_schema_v1() -> None:
    j = InMemoryJournal()
    ref = j.put_payload(b"abc", content_type="text/plain", kind="note")
    j.append(
        JournalEvent(
            event_id="e1",
            ts_ms=1,
            type=EVENT_NOTE,
            component="test",
            turn_id="t1",
            span_id=None,
            parent_span_id=None,
            data={"msg": "hi"},
            payload_refs=(ref,),
        )
    )
    exp = j.export()
    d = exp.to_dict()
    assert d["journal_schema"] == JOURNAL_SCHEMA_VERSION == 1
    assert len(d["events"]) == 1
    assert d["events"][0]["type"] == EVENT_NOTE
    assert d["events"][0]["payload_refs"] == [ref]
    assert ref in d["payloads"]
    assert d["payloads"][ref]["size"] == 3
    assert d["payloads"][ref]["sha256"]


def test_span_parent_linkage() -> None:
    j = InMemoryJournal()
    clock = {"t": 1000}

    def now() -> int:
        clock["t"] += 1
        return clock["t"]

    tracer = SpanTracer(journal=j, turn_id="turn_x", _clock_ms=now)
    root = tracer.start("turn")
    child = tracer.start("zeus.hop")
    tracer.end(child, status="ok")
    tracer.end(root, status="ok")

    events = list(j.events())
    types = [e.type for e in events]
    assert types == [
        EVENT_SPAN_STARTED,
        EVENT_SPAN_STARTED,
        EVENT_SPAN_ENDED,
        EVENT_SPAN_ENDED,
    ]
    assert events[0].span_id == root.span_id
    assert events[0].parent_span_id is None
    assert events[1].span_id == child.span_id
    assert events[1].parent_span_id == root.span_id
    assert events[2].span_id == child.span_id
    assert events[2].parent_span_id == root.span_id
    assert events[3].span_id == root.span_id


def test_job_and_unit_lifecycle_event_types() -> None:
    assert EVENT_JOB_STARTED == "job.started"
    assert EVENT_JOB_FINISHED == "job.finished"
    assert EVENT_UNIT_STARTED == "unit.started"
    assert EVENT_UNIT_FINISHED == "unit.finished"
    j = InMemoryJournal()
    j.append(_evt("j1", 1, EVENT_JOB_STARTED, data={"job_id": "job_1", "llm.role": "worker"}))
    j.append(_evt("u1", 2, EVENT_UNIT_STARTED, data={"unit_id": "u1", "llm.model": "fast"}))
    j.append(_evt("u2", 3, EVENT_UNIT_FINISHED, data={"unit_id": "u1", "status": "ok"}))
    j.append(_evt("j2", 4, EVENT_JOB_FINISHED, data={"job_id": "job_1", "status": "ok"}))
    types = [e.type for e in j.events()]
    assert types == [
        EVENT_JOB_STARTED,
        EVENT_UNIT_STARTED,
        EVENT_UNIT_FINISHED,
        EVENT_JOB_FINISHED,
    ]
    dumped = str([dict(e.data) for e in j.events()])
    assert "password" not in dumped
    assert "sk-" not in dumped
