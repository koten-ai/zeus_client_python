"""Journal event types and frozen JournalEvent (schema v1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "JournalEvent",
    "EVENT_TURN_STARTED",
    "EVENT_TURN_COMPLETED",
    "EVENT_SPAN_STARTED",
    "EVENT_SPAN_ENDED",
    "EVENT_ERROR_RAISED",
    "EVENT_NOTE",
    "EVENT_ZEUS_HOP",
    "EVENT_LLM_ROUND",
]

EVENT_TURN_STARTED = "turn.started"
EVENT_TURN_COMPLETED = "turn.completed"
EVENT_SPAN_STARTED = "span.started"
EVENT_SPAN_ENDED = "span.ended"
EVENT_ERROR_RAISED = "error.raised"
EVENT_NOTE = "note"
EVENT_ZEUS_HOP = "zeus.hop"
EVENT_LLM_ROUND = "llm.round"


@dataclass(frozen=True, slots=True)
class JournalEvent:
    """Immutable journal row — bodies already redacted; large blobs via payload_refs."""

    event_id: str
    ts_ms: int
    type: str
    component: str
    turn_id: str
    span_id: str | None
    parent_span_id: str | None
    data: Mapping[str, Any]
    payload_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Freeze mapping as plain dict copy so callers cannot mutate after append.
        object.__setattr__(self, "data", dict(self.data))
        if self.payload_refs is None:
            object.__setattr__(self, "payload_refs", ())
        else:
            object.__setattr__(self, "payload_refs", tuple(self.payload_refs))
