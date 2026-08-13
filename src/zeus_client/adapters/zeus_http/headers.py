"""V2 Zeus HTTP header helpers — mode, correlation, product stamp."""

from __future__ import annotations

from typing import Mapping

from zeus_client._version import __version__ as PACKAGE_VERSION

__all__ = [
    "apply_mode_header",
    "apply_force_trace_header",
    "correlation_headers",
    "product_stamp_headers",
    "merge_headers",
]

_PRODUCT_USER = "zeus_client"


def apply_mode_header(headers: Mapping[str, str] | None, mode: str | None) -> dict[str, str]:
    h = dict(headers or {})
    m = (mode or "").strip()
    if not m:
        return h
    if "X-Zeus-Mode" not in h and "x-zeus-mode" not in {k.lower() for k in h}:
        h["X-Zeus-Mode"] = m
    return h


def apply_force_trace_header(headers: Mapping[str, str] | None, force: bool) -> dict[str, str]:
    h = dict(headers or {})
    if force:
        h["X-Zeus-Trace"] = "1"
    return h


def correlation_headers(
    *,
    chat_id: str = "",
    turn_id: str = "",
    call_id: str = "",
    mode: str = "",
    force_trace: bool = False,
) -> dict[str, str]:
    h: dict[str, str] = {}
    if chat_id:
        h["X-Zeus-Chat-Id"] = str(chat_id)
    if turn_id:
        h["X-Zeus-Turn-Id"] = str(turn_id)
    if call_id:
        h["X-Zeus-Call-Id"] = str(call_id)
    if mode:
        h["X-Zeus-Mode"] = str(mode)
    if force_trace:
        h["X-Zeus-Trace"] = "1"
    return h


def product_stamp_headers(*, version: str | None = None) -> dict[str, str]:
    """Stamp product identity (never secrets)."""
    return {
        "X-Zeus-Client": _PRODUCT_USER,
        "X-Zeus-Client-Version": version or PACKAGE_VERSION,
    }


def merge_headers(*parts: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in parts:
        if p:
            out.update(dict(p))
    return out
