"""Optional OTLP Logs exporter (CHECKLIST D). Soft-fails without OpenTelemetry pkgs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = ["OTLPExporter", "NullOTLPExporter", "try_build_otlp_exporter"]


class NullOTLPExporter:
    """No-op exporter (default)."""

    enabled: bool = False

    def export_events(self, events: Sequence[Mapping[str, Any]]) -> int:
        return 0

    def attach_log_handler(self, logger_name: str = "zeus_client") -> bool:
        return False

    def shutdown(self) -> None:
        return None


@dataclass
class OTLPExporter:
    """Best-effort OTLP Logs projection. Soft-fails if OpenTelemetry is absent."""

    endpoint: str
    service_name: str = "zeus_client"
    enabled: bool = True
    _notes: list[str] = field(default_factory=list, repr=False)
    _provider: Any = field(default=None, repr=False)
    _handler: Any = field(default=None, repr=False)

    def export_events(self, events: Sequence[Mapping[str, Any]]) -> int:
        if not self.enabled or not events:
            return 0
        n = 0
        for ev in events:
            if isinstance(ev, Mapping):
                n += 1
        return n

    def attach_log_handler(self, logger_name: str = "zeus_client") -> bool:
        if not self.enabled or not self.endpoint:
            return False
        try:
            from opentelemetry import _logs as otel_logs
            from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                OTLPLogExporter,
            )
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.resources import Resource
        except Exception as exc:  # noqa: BLE001 — optional extra
            self._notes.append(f"otlp_import_failed:{type(exc).__name__}")
            return False
        try:
            resource = Resource.create({"service.name": self.service_name})
            provider = LoggerProvider(resource=resource)
            exporter = OTLPLogExporter(endpoint=self.endpoint)
            provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            otel_logs.set_logger_provider(provider)
            handler = LoggingHandler(level=0, logger_provider=provider)
            import logging

            logging.getLogger(logger_name).addHandler(handler)
            self._provider = provider
            self._handler = handler
            return True
        except Exception as exc:  # noqa: BLE001
            self._notes.append(f"otlp_attach_failed:{type(exc).__name__}")
            return False

    def shutdown(self) -> None:
        if self._handler is not None:
            try:
                import logging

                logging.getLogger("zeus_client").removeHandler(self._handler)
            except Exception:
                pass
            self._handler = None
        if self._provider is not None and hasattr(self._provider, "shutdown"):
            try:
                self._provider.shutdown()
            except Exception:
                pass
            self._provider = None


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
    exp = OTLPExporter(endpoint=ep, service_name=service_name, enabled=True)
    exp.attach_log_handler()
    return exp
