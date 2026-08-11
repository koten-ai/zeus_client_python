"""Journal export schema v1 — JSON-serializable snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from zeus_client_v2.domain.journal.journal import ExecutionJournal

__all__ = ["JournalExport", "export_journal", "JOURNAL_SCHEMA_VERSION"]

JOURNAL_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class JournalExport:
    """Versioned export envelope."""

    journal_schema: int
    events: tuple[Mapping[str, Any], ...]
    payloads: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_schema": self.journal_schema,
            "events": [dict(e) for e in self.events],
            "payloads": {k: dict(v) for k, v in self.payloads.items()},
        }


def export_journal(journal: ExecutionJournal) -> JournalExport:
    """Serialize journal events (+ payload metadata, not necessarily full bytes)."""
    events_out: list[dict[str, Any]] = []
    for ev in journal.events():
        events_out.append(
            {
                "event_id": ev.event_id,
                "ts_ms": ev.ts_ms,
                "type": ev.type,
                "component": ev.component,
                "turn_id": ev.turn_id,
                "span_id": ev.span_id,
                "parent_span_id": ev.parent_span_id,
                "data": dict(ev.data),
                "payload_refs": list(ev.payload_refs),
            }
        )

    payloads_meta: dict[str, dict[str, Any]] = {}
    store = getattr(journal, "payload_store", None)
    if store is not None and hasattr(store, "items"):
        for ref, rec in store.items().items():
            payloads_meta[ref] = {
                "ref": rec.ref,
                "content_type": rec.content_type,
                "kind": rec.kind,
                "sha256": rec.sha256,
                "size": rec.size,
            }

    return JournalExport(
        journal_schema=JOURNAL_SCHEMA_VERSION,
        events=tuple(events_out),
        payloads=payloads_meta,
    )
