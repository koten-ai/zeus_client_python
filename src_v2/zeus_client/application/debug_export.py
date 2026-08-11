"""Debug export helpers — redacted journal snapshots + span trees (ZCM-020)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from zeus_client_v2.domain.journal.events import EVENT_SPAN_ENDED, EVENT_SPAN_STARTED
from zeus_client_v2.domain.journal.export import (
    JOURNAL_SCHEMA_VERSION,
    JournalExport,
    export_journal,
)
from zeus_client_v2.domain.journal.journal import ExecutionJournal, InMemoryJournal
from zeus_client_v2.security.redact import DefaultRedactor, default_redactor

__all__ = [
    "SpanNode",
    "SpanTree",
    "export_journal_redacted",
    "filter_export_by_turn",
    "build_span_tree",
    "event_type_sequence",
    "mermaid_timeline",
]


@dataclass(frozen=True, slots=True)
class SpanNode:
    span_id: str
    name: str
    parent_span_id: str | None
    turn_id: str
    started_ts_ms: int | None = None
    ended_ts_ms: int | None = None
    status: str | None = None
    children: tuple["SpanNode", ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "parent_span_id": self.parent_span_id,
            "turn_id": self.turn_id,
            "started_ts_ms": self.started_ts_ms,
            "ended_ts_ms": self.ended_ts_ms,
            "status": self.status,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass(frozen=True, slots=True)
class SpanTree:
    roots: tuple[SpanNode, ...] = ()
    turn_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "roots": [r.to_dict() for r in self.roots],
        }


def filter_export_by_turn(export: JournalExport, turn_id: str | None) -> JournalExport:
    """Return export filtered to one turn (or unchanged if turn_id is None)."""
    if not turn_id:
        return export
    events = tuple(e for e in export.events if str(e.get("turn_id") or "") == turn_id)
    # Keep all payload meta refs that appear in filtered events
    refs: set[str] = set()
    for e in events:
        for r in e.get("payload_refs") or ():
            refs.add(str(r))
    payloads = {k: v for k, v in export.payloads.items() if k in refs} if refs else {}
    return JournalExport(
        journal_schema=export.journal_schema,
        events=events,
        payloads=payloads,
    )


def export_journal_redacted(
    journal: ExecutionJournal,
    *,
    turn_id: str | None = None,
    redactor: DefaultRedactor | None = None,
) -> JournalExport:
    """Export journal with nested JSON values redacted (no secrets in dump)."""
    red = redactor or default_redactor()
    raw = export_journal(journal)
    filtered = filter_export_by_turn(raw, turn_id)
    events_out: list[dict[str, Any]] = []
    for ev in filtered.events:
        data = red.json_value(dict(ev.get("data") or {}))
        if not isinstance(data, dict):
            data = {"_": data}
        events_out.append(
            {
                "event_id": ev.get("event_id"),
                "ts_ms": ev.get("ts_ms"),
                "type": ev.get("type"),
                "component": ev.get("component"),
                "turn_id": ev.get("turn_id"),
                "span_id": ev.get("span_id"),
                "parent_span_id": ev.get("parent_span_id"),
                "data": data,
                "payload_refs": list(ev.get("payload_refs") or ()),
            }
        )
    return JournalExport(
        journal_schema=filtered.journal_schema or JOURNAL_SCHEMA_VERSION,
        events=tuple(events_out),
        payloads=dict(filtered.payloads),
    )


def event_type_sequence(
    export: JournalExport | Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    turn_id: str | None = None,
) -> tuple[str, ...]:
    """Ordered event ``type`` strings — greentest / transport replay fingerprint."""
    if isinstance(export, JournalExport):
        events = filter_export_by_turn(export, turn_id).events
    elif isinstance(export, Mapping) and "events" in export:
        events = export.get("events") or ()
        if turn_id:
            events = [e for e in events if isinstance(e, Mapping) and e.get("turn_id") == turn_id]
    else:
        events = export  # type: ignore[assignment]
    out: list[str] = []
    for e in events:
        if isinstance(e, Mapping) and e.get("type"):
            out.append(str(e["type"]))
    return tuple(out)


def build_span_tree(
    export: JournalExport | Mapping[str, Any] | ExecutionJournal,
    *,
    turn_id: str | None = None,
) -> SpanTree:
    """Build parent-linked span tree from span.started / span.ended events."""
    if isinstance(export, ExecutionJournal):
        exp = export_journal(export)
    elif isinstance(export, JournalExport):
        exp = export
    else:
        exp = JournalExport(
            journal_schema=int(export.get("journal_schema") or 1),
            events=tuple(export.get("events") or ()),
            payloads=dict(export.get("payloads") or {}),
        )
    exp = filter_export_by_turn(exp, turn_id)

    started: dict[str, dict[str, Any]] = {}
    ended: dict[str, dict[str, Any]] = {}
    for ev in exp.events:
        if not isinstance(ev, Mapping):
            continue
        sid = ev.get("span_id")
        if not sid:
            continue
        sid = str(sid)
        typ = ev.get("type")
        if typ == EVENT_SPAN_STARTED:
            started[sid] = dict(ev)
        elif typ == EVENT_SPAN_ENDED:
            ended[sid] = dict(ev)

    nodes: dict[str, SpanNode] = {}
    for sid, sev in started.items():
        eev = ended.get(sid) or {}
        data_s = sev.get("data") if isinstance(sev.get("data"), Mapping) else {}
        data_e = eev.get("data") if isinstance(eev.get("data"), Mapping) else {}
        name = str(data_s.get("name") or data_e.get("name") or sid)
        nodes[sid] = SpanNode(
            span_id=sid,
            name=name,
            parent_span_id=str(sev["parent_span_id"])
            if sev.get("parent_span_id")
            else None,
            turn_id=str(sev.get("turn_id") or ""),
            started_ts_ms=int(sev["ts_ms"]) if sev.get("ts_ms") is not None else None,
            ended_ts_ms=int(eev["ts_ms"]) if eev.get("ts_ms") is not None else None,
            status=str(data_e["status"]) if data_e.get("status") is not None else None,
            children=(),
        )

    # attach children
    children_map: dict[str | None, list[SpanNode]] = {}
    for n in nodes.values():
        children_map.setdefault(n.parent_span_id, []).append(n)

    def _with_children(n: SpanNode) -> SpanNode:
        kids = tuple(_with_children(c) for c in children_map.get(n.span_id, ()))
        return SpanNode(
            span_id=n.span_id,
            name=n.name,
            parent_span_id=n.parent_span_id,
            turn_id=n.turn_id,
            started_ts_ms=n.started_ts_ms,
            ended_ts_ms=n.ended_ts_ms,
            status=n.status,
            children=kids,
        )

    roots = tuple(_with_children(n) for n in children_map.get(None, ()))
    # orphan parents that reference missing span still surface as roots
    known = set(nodes)
    for n in nodes.values():
        if n.parent_span_id and n.parent_span_id not in known:
            # already only under None if parent missing — re-check
            if n.span_id not in {r.span_id for r in roots} and all(
                n.span_id != c.span_id for r in roots for c in _walk(r)
            ):
                roots = roots + (_with_children(n),)

    return SpanTree(roots=roots, turn_id=turn_id)


def _walk(n: SpanNode):
    yield n
    for c in n.children:
        yield from _walk(c)


def mermaid_timeline(
    export: JournalExport | Mapping[str, Any] | ExecutionJournal,
    *,
    turn_id: str | None = None,
) -> str:
    """Optional Mermaid sequence-ish flowchart of span tree (debug only)."""
    tree = build_span_tree(export, turn_id=turn_id)
    lines = ["flowchart TD"]
    if not tree.roots:
        lines.append("  empty[no spans]")
        return "\n".join(lines) + "\n"

    def emit(n: SpanNode, parent: str | None = None) -> None:
        nid = n.span_id.replace("-", "_")
        label = n.name.replace('"', "'")
        st = f" ({n.status})" if n.status else ""
        lines.append(f'  {nid}["{label}{st}"]')
        if parent:
            lines.append(f"  {parent} --> {nid}")
        for c in n.children:
            emit(c, nid)

    for r in tree.roots:
        emit(r, None)
    return "\n".join(lines) + "\n"
