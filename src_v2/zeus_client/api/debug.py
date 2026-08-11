"""Public debug facade — journal export, spans, transport replay (ZCP-20)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

from zeus_client_v2.application.debug_export import (
    SpanTree,
    build_span_tree,
    event_type_sequence,
    export_journal_redacted,
    mermaid_timeline,
)
from zeus_client_v2.application.replay import (
    ReplayMode,
    ReplayResult,
    transport_replay,
)
from zeus_client_v2.domain.journal.export import JournalExport

if TYPE_CHECKING:
    from zeus_client_v2.runtime import ZeusRuntime

__all__ = ["DebugAPI"]


class DebugAPI:
    """``rt.debug.export_journal()`` / ``spans()`` / ``replay()``."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    def export_journal(
        self,
        turn_id: str | None = None,
        *,
        redact: bool = True,
    ) -> JournalExport:
        """Export journal snapshot. Default redacts nested sensitive keys."""
        journal = self._rt.journal
        if redact:
            redactor = getattr(self._rt.services, "redactor", None)
            return export_journal_redacted(
                journal, turn_id=turn_id, redactor=redactor
            )
        from zeus_client_v2.domain.journal.export import export_journal
        from zeus_client_v2.application.debug_export import filter_export_by_turn

        return filter_export_by_turn(export_journal(journal), turn_id)

    def spans(self, turn_id: str | None = None) -> SpanTree:
        return build_span_tree(self._rt.journal, turn_id=turn_id)

    def mermaid_timeline(self, turn_id: str | None = None) -> str:
        return mermaid_timeline(self._rt.journal, turn_id=turn_id)

    def event_types(self, turn_id: str | None = None) -> tuple[str, ...]:
        exp = self.export_journal(turn_id=turn_id, redact=True)
        return event_type_sequence(exp)

    async def replay(
        self,
        export: JournalExport | Mapping[str, Any] | None = None,
        *,
        mode: ReplayMode | str = ReplayMode.TRANSPORT,
        expected_types: Sequence[str] | None = None,
        turn_id: str | None = None,
        allow_extra: bool = False,
    ) -> ReplayResult:
        """Transport replay greentest (offline). ``mode=agent`` not implemented yet."""
        m = ReplayMode(mode) if not isinstance(mode, ReplayMode) else mode
        if m is ReplayMode.AGENT:
            return ReplayResult(
                ok=False,
                mode=m,
                turn_id=turn_id,
                actual_types=(),
                expected_types=tuple(expected_types) if expected_types else None,
                errors=("agent replay mode not implemented in ZCP-20; use transport",),
            )
        source = export if export is not None else self._rt.journal
        return transport_replay(
            source,
            expected_types=expected_types,
            turn_id=turn_id,
            allow_extra=allow_extra,
        )
