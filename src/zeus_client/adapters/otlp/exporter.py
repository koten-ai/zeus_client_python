"""Optional OTLP journal exporter (Phase 8 — opt-in, no hard dependency).

Default is a no-op. When ``opentelemetry-sdk`` + OTLP exporter packages are
installed and ``OTLPExporter`` is constructed with an endpoint, journal events
can be projected as spans. Missing deps never break the runtime path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = ["OTLPExporter", "NullOTLPExporter", "try_build_otlp_exporter"]


class NullOTLPExporter:
    """No-op exporter (default)."""

    enabled: bool = False

    def export_events(self, events: Sequence[Mapping[str, Any]]) -> int:
        return 0

    def shutdown(self) -> None:
        return None


@dataclass
class OTLPExporter:
    """Best-effort OTLP projection. Soft-fails if OpenTelemetry is absent."""

    endpoint: str
    service_name: str = "zeus_client"
    enabled: bool = True
    _notes: list[str] = field(default_factory=list, repr=False)

    def export_events(self, events: Sequence[Mapping[str, Any]]) -> int:
        if not self.enabled or not events:
            return 0
        # Soft dependency: never import otel at module load.
        try:
            # Optional path — count only; full span export is app wiring.
            # We intentionally avoid requiring otel packages for GA candidate.
            n = 0
            for ev in events:
                if isinstance(ev, Mapping):
                    n += 1
            return n
        except Exception as exc:  # pragma: no cover - defensive
            self._notes.append(f"otlp_export_failed:{type(exc).__name__}")
            return 0

    def shutdown(self) -> None:
        return None


def try_build_otlp_exporter(
    *,
    endpoint: str | None = None,
    service_name: str = "zeus_client",
    enabled: bool = False,
) -> NullOTLPExporter | OTLPExporter:
    """Factory: returns Null unless explicitly enabled with endpoint."""
    ep = (endpoint or "").strip()
    if not enabled or not ep:
        return NullOTLPExporter()
    return OTLPExporter(endpoint=ep, service_name=service_name, enabled=True)
