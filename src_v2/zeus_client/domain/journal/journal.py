"""Append-only ExecutionJournal over an optional PayloadStore."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from zeus_client_v2.domain.journal.events import JournalEvent
from zeus_client_v2.domain.journal.export import JournalExport, export_journal
from zeus_client_v2.domain.journal.payload_store import InMemoryPayloadStore, PayloadStore

__all__ = ["ExecutionJournal", "InMemoryJournal"]


class ExecutionJournal:
    """Protocol-shaped journal API."""

    def append(self, event: JournalEvent) -> None:
        raise NotImplementedError

    def events(self) -> Sequence[JournalEvent]:
        raise NotImplementedError

    def get_payload(self, ref: str) -> bytes | None:
        raise NotImplementedError

    def export(self) -> JournalExport:
        raise NotImplementedError


@dataclass
class InMemoryJournal(ExecutionJournal):
    """Mutable append-only list of frozen events + payload store."""

    payload_store: PayloadStore = field(default_factory=InMemoryPayloadStore)
    _events: list[JournalEvent] = field(default_factory=list)

    def append(self, event: JournalEvent) -> None:
        if not isinstance(event, JournalEvent):
            raise TypeError("event must be JournalEvent")
        # Copy-on-append already frozen; store reference.
        self._events.append(event)

    def events(self) -> Sequence[JournalEvent]:
        return tuple(self._events)

    def get_payload(self, ref: str) -> bytes | None:
        return self.payload_store.get(ref)

    def put_payload(self, data: bytes, *, content_type: str = "application/octet-stream", kind: str = "blob") -> str:
        return self.payload_store.put(data, content_type=content_type, kind=kind)

    def export(self) -> JournalExport:
        return export_journal(self)
