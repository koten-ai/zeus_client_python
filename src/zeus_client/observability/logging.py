"""Family logger — INFO/ERROR/DEBUG/TRACE, REDACT, dotted ``zeus_client.*`` events.

Journal event types stay internal (``turn.started``). This module is the
LOGGING.md bridge for operators (Loki / OTel Logs).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableSequence
from typing import Any

from zeus_client.security.redact import DefaultRedactor, default_redactor

__all__ = [
    "TRACE",
    "FAMILY_LEVELS",
    "FamilyLogger",
    "configure_family_logger",
    "get_family_logger",
    "redact_attrs",
    "CaptureLogHandler",
]

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

FAMILY_LEVELS: dict[str, int] = {
    "error": logging.ERROR,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": TRACE,
}

_LOGGER_NAME = "zeus_client"
_MAX_STR = 2048
_HARD_KEYS = frozenset(
    {
        "authorization",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "token",
        "refresh_token",
        "private_key",
        "cookie",
    }
)


def _level_num(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return FAMILY_LEVELS.get(str(level).strip().lower(), logging.INFO)


def redact_attrs(
    attrs: Mapping[str, Any] | None,
    *,
    redact: bool = True,
    redactor: DefaultRedactor | None = None,
    preview_max_chars: int = _MAX_STR,
) -> dict[str, Any]:
    """Redact once at the logging boundary. Secrets stay denied when REDACT=false."""
    red = redactor or default_redactor()
    out: dict[str, Any] = {}
    for raw_k, v in (attrs or {}).items():
        if v is None:
            continue
        key = str(raw_k)
        lk = key.lower().replace(".", "_").replace("-", "_")
        if any(h in lk for h in _HARD_KEYS) or lk in _HARD_KEYS:
            out[key] = "[REDACTED]"
            continue
        walked = red.json_value(v)
        if redact and isinstance(walked, str) and preview_max_chars >= 0:
            out[key] = red.text(walked, max_chars=preview_max_chars)
        elif isinstance(walked, str) and len(walked) > 16_384:
            out[key] = walked[:16_384] + "…"
        else:
            out[key] = walked
    return out


class CaptureLogHandler(logging.Handler):
    """Test helper: store ``(levelname, event, attrs)`` tuples."""

    def __init__(self, sink: MutableSequence[dict[str, Any]]) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        attrs = getattr(record, "zeus_attrs", None)
        if not isinstance(attrs, dict):
            attrs = {}
        self.sink.append(
            {
                "level": (record.levelname or "").upper(),
                "event": record.getMessage(),
                "attrs": dict(attrs),
            }
        )


class FamilyLogger:
    """Emit stable dotted events with structured primitive attrs."""

    def __init__(
        self,
        *,
        level: str = "info",
        redact: bool = True,
        service_name: str = "zeus_client",
        service_version: str = "",
        redactor: DefaultRedactor | None = None,
        logger: logging.Logger | None = None,
        preview_max_chars: int = _MAX_STR,
    ) -> None:
        self.redact = bool(redact)
        self.service_name = service_name
        self.service_version = service_version
        self._redactor = redactor or default_redactor()
        self._preview = int(preview_max_chars)
        self._logger = logger or logging.getLogger(_LOGGER_NAME)
        self.set_level(level)

    def set_level(self, level: str | int) -> None:
        self._logger.setLevel(_level_num(level))

    def emit(self, severity: str, event: str, **attrs: Any) -> None:
        num = _level_num(severity)
        if not self._logger.isEnabledFor(num):
            return
        # stdlib LogRecord reserves ``level``; family attr is ``log.level``.
        if "level" in attrs:
            attrs = dict(attrs)
            attrs["log.level"] = attrs.pop("level")
        merged: dict[str, Any] = {
            "service.name": self.service_name,
            **attrs,
        }
        if self.service_version:
            merged["service.version"] = self.service_version
        safe = redact_attrs(
            merged,
            redact=self.redact,
            redactor=self._redactor,
            preview_max_chars=self._preview,
        )
        self._logger.log(num, event, extra={"zeus_attrs": safe, "event_name": event})

    def info(self, event: str, **attrs: Any) -> None:
        self.emit("info", event, **attrs)

    def error(self, event: str, **attrs: Any) -> None:
        self.emit("error", event, **attrs)

    def debug(self, event: str, **attrs: Any) -> None:
        self.emit("debug", event, **attrs)

    def trace(self, event: str, **attrs: Any) -> None:
        self.emit("trace", event, **attrs)


_default: FamilyLogger | None = None
_configured_redact_false_logged = False


def get_family_logger() -> FamilyLogger:
    global _default
    if _default is None:
        _default = FamilyLogger()
    return _default


def configure_family_logger(
    *,
    level: str = "info",
    redact: bool = True,
    service_name: str = "zeus_client",
    service_version: str = "",
    preview_max_chars: int = _MAX_STR,
    redactor: DefaultRedactor | None = None,
) -> FamilyLogger:
    """Bind process logger. Logs loudly once when REDACT=false."""
    global _default, _configured_redact_false_logged
    log = FamilyLogger(
        level=level,
        redact=redact,
        service_name=service_name,
        service_version=service_version,
        redactor=redactor,
        preview_max_chars=preview_max_chars,
    )
    _default = log
    if not redact:
        _configured_redact_false_logged = True
    log.info(
        "zeus_client.logging.configured",
        **{"result": "ok", "level": str(level).lower(), "redact": bool(redact)},
    )
    return log
