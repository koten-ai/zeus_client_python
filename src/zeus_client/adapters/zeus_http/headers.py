"""V2 Zeus HTTP header helpers — mode, correlation, product stamp, rewind."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zeus_client._version import __version__ as PACKAGE_VERSION

__all__ = [
    "TRACE_CLASS_AGENT",
    "TRACE_CLASS_SESSION",
    "TRACE_CLASS_DIRECT_INTERACTIVE",
    "TRACE_CLASS_DIRECT_READ",
    "TRACE_CLASS_DIRECT_BATCH",
    "apply_mode_header",
    "apply_force_trace_header",
    "correlation_headers",
    "product_stamp_headers",
    "merge_headers",
    "req_id_from_headers",
    "rewind_query_params",
    "verb_body_without_rewind",
]

TRACE_CLASS_AGENT = "agent"
TRACE_CLASS_SESSION = "session"
TRACE_CLASS_DIRECT_INTERACTIVE = "direct.interactive"
TRACE_CLASS_DIRECT_READ = "direct.read"
TRACE_CLASS_DIRECT_BATCH = "direct.batch"

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
    trace_class: str = "",
    chat_session_id: str = "",
    brief_sha12: str = "",
    mini_sha12: str = "",
) -> dict[str, str]:
    """Rewind / join correlation. Never sets ``X-Zeus-Session`` or ``X-Zeus-Req-Id``."""
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
    tc = (trace_class or "").strip()
    if tc:
        h["X-Zeus-Trace-Class"] = tc
    sid = (chat_session_id or "").strip()
    if sid:
        h["X-Zeus-Chat-Session-Id"] = sid
    brief = (brief_sha12 or "").strip()
    if brief:
        h["X-Zeus-Brief-Sha12"] = brief
    mini = (mini_sha12 or "").strip()
    if mini:
        h["X-Zeus-Mini-Sha12"] = mini
    return h


def product_stamp_headers(*, version: str | None = None) -> dict[str, str]:
    """Stamp product identity (never secrets)."""
    return {
        "X-Zeus-Client": _PRODUCT_USER,
        "X-Zeus-Client-Version": version or PACKAGE_VERSION,
    }


def req_id_from_headers(headers: Mapping[str, str] | None) -> str | None:
    """Full ``X-Zeus-Req-Id`` (never truncated). None when absent."""
    if not headers:
        return None
    for key, val in headers.items():
        if str(key).lower() == "x-zeus-req-id":
            text = str(val or "").strip()
            return text or None
    return None


def merge_headers(*parts: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in parts:
        if p:
            out.update(dict(p))
    return out


def rewind_query_params(rewind: bool) -> dict[str, str]:
    """Query ``rewind=true`` so Zeus persists a verbose tape (ZCP-112). Empty when off."""
    return {"rewind": "true"} if rewind else {}


def verb_body_without_rewind(body: Mapping[str, Any] | None) -> dict[str, Any]:
    """Drop ``rewind`` from verb JSON — it is a query/session flag, not a Zeus arg."""
    out = dict(body or {})
    out.pop("rewind", None)
    return out
