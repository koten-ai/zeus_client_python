"""Transport replay harness — offline event-sequence greentests (ZCM-022).

``mode=transport`` does **not** re-hit Zeus/LLM. It validates that a journal
export (or live journal) carries an expected ordered event-type fingerprint
for a scripted dialogue. Full agent re-execution is agent-turn + fakes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from zeus_client.application.debug_export import (
    event_type_sequence,
    filter_export_by_turn,
)
from zeus_client.domain.journal.export import JournalExport, export_journal
from zeus_client.domain.journal.journal import ExecutionJournal

__all__ = [
    "ReplayMode",
    "ReplayResult",
    "transport_replay",
    "assert_event_type_sequence",
    "load_export",
]


class ReplayMode(str, Enum):
    TRANSPORT = "transport"
    # Reserved: full agent re-run with recorded fakes (not required for ZCP-20)
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class ReplayResult:
    ok: bool
    mode: ReplayMode
    turn_id: str | None
    actual_types: tuple[str, ...]
    expected_types: tuple[str, ...] | None = None
    errors: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode.value,
            "turn_id": self.turn_id,
            "actual_types": list(self.actual_types),
            "expected_types": list(self.expected_types or ()),
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


def load_export(
    source: JournalExport | Mapping[str, Any] | ExecutionJournal,
) -> JournalExport:
    if isinstance(source, JournalExport):
        return source
    if isinstance(source, ExecutionJournal):
        return export_journal(source)
    if isinstance(source, Mapping):
        return JournalExport(
            journal_schema=int(source.get("journal_schema") or 1),
            events=tuple(source.get("events") or ()),
            payloads=dict(source.get("payloads") or {}),
        )
    raise TypeError(f"unsupported export source: {type(source)!r}")


def assert_event_type_sequence(
    actual: Sequence[str],
    expected: Sequence[str],
    *,
    allow_extra: bool = False,
) -> list[str]:
    """Compare sequences. If allow_extra, expected must be an ordered subsequence."""
    errors: list[str] = []
    a = list(actual)
    e = list(expected)
    if not allow_extra:
        if a != e:
            errors.append(f"type sequence mismatch: actual={a!r} expected={e!r}")
        return errors
    # subsequence match
    i = 0
    for typ in a:
        if i < len(e) and typ == e[i]:
            i += 1
    if i != len(e):
        errors.append(
            f"expected types not found in order as subsequence: "
            f"matched={i}/{len(e)} actual={a!r} expected={e!r}"
        )
    return errors


def transport_replay(
    source: JournalExport | Mapping[str, Any] | ExecutionJournal,
    *,
    expected_types: Sequence[str] | None = None,
    turn_id: str | None = None,
    allow_extra: bool = False,
    require_non_empty: bool = True,
) -> ReplayResult:
    """Offline transport greentest over journal event types."""
    exp = load_export(source)
    exp = filter_export_by_turn(exp, turn_id)
    actual = event_type_sequence(exp)
    notes: list[str] = [f"events={len(exp.events)}", f"schema={exp.journal_schema}"]
    errors: list[str] = []

    if require_non_empty and not actual:
        errors.append("empty event type sequence")

    expected_t = tuple(expected_types) if expected_types is not None else None
    if expected_t is not None:
        errors.extend(assert_event_type_sequence(actual, expected_t, allow_extra=allow_extra))
    else:
        notes.append("no expected_types — sequence captured only")

    return ReplayResult(
        ok=not errors,
        mode=ReplayMode.TRANSPORT,
        turn_id=turn_id,
        actual_types=actual,
        expected_types=expected_t,
        errors=tuple(errors),
        notes=tuple(notes),
    )
