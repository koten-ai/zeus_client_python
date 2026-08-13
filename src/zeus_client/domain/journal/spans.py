"""Span start/end helpers linked into the ExecutionJournal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from zeus_client.domain.journal.events import (
    EVENT_SPAN_ENDED,
    EVENT_SPAN_STARTED,
    JournalEvent,
)
from zeus_client.domain.journal.journal import ExecutionJournal

__all__ = ["SpanTracer", "SpanHandle"]


@dataclass(frozen=True, slots=True)
class SpanHandle:
    span_id: str
    parent_span_id: str | None
    name: str
    turn_id: str


@dataclass
class SpanTracer:
    """Open/close spans as journal events with parent linkage."""

    journal: ExecutionJournal
    turn_id: str
    component: str = "domain.journal.spans"
    _stack: list[str] = field(default_factory=list)
    _clock_ms: Any = None  # optional callable () -> int

    def _now(self) -> int:
        if self._clock_ms is not None:
            return int(self._clock_ms())
        import time

        return int(time.time() * 1000)

    def _new_span_id(self) -> str:
        return f"span_{uuid.uuid4().hex[:16]}"

    def start(
        self,
        name: str,
        *,
        parent_span_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> SpanHandle:
        if parent_span_id is None and self._stack:
            parent_span_id = self._stack[-1]
        span_id = self._new_span_id()
        handle = SpanHandle(
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            turn_id=self.turn_id,
        )
        self.journal.append(
            JournalEvent(
                event_id=f"evt_{uuid.uuid4().hex[:16]}",
                ts_ms=self._now(),
                type=EVENT_SPAN_STARTED,
                component=self.component,
                turn_id=self.turn_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                data={"name": name, **dict(data or {})},
            )
        )
        self._stack.append(span_id)
        return handle

    def end(
        self,
        handle: SpanHandle,
        *,
        data: Mapping[str, Any] | None = None,
        status: str = "ok",
    ) -> None:
        if self._stack and self._stack[-1] == handle.span_id:
            self._stack.pop()
        elif handle.span_id in self._stack:
            self._stack.remove(handle.span_id)
        self.journal.append(
            JournalEvent(
                event_id=f"evt_{uuid.uuid4().hex[:16]}",
                ts_ms=self._now(),
                type=EVENT_SPAN_ENDED,
                component=self.component,
                turn_id=handle.turn_id,
                span_id=handle.span_id,
                parent_span_id=handle.parent_span_id,
                data={"name": handle.name, "status": status, **dict(data or {})},
            )
        )
