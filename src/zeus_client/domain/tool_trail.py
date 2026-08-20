"""Slim Zeus hop trail for later LLM rounds (CHECKLIST B · AGENT_TOOL_TRAIL)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "TRAIL_HEADING",
    "trail_entry_from_hop",
    "render_trail_inject",
    "upsert_trail_on_system",
    "error_class_for",
]

TRAIL_HEADING = "ZEUS_TOOL_TRAIL (this turn):"


def error_class_for(*, ok: bool, status: int, error: str | None = None) -> str | None:
    if ok:
        return None
    if status == 409:
        return "contract_mismatch"
    if status in {429, 503} or (error and "timeout" in str(error).lower()):
        return "retryable_later"
    if 400 <= int(status or 0) < 500:
        return "do_not_retry_same_args"
    return "zeus_error"


def _hint(*, ok: bool, status: int, empty: bool, error_class: str | None) -> str | None:
    if ok and empty:
        return "empty"
    if ok:
        return "success"
    if error_class == "contract_mismatch" or error_class == "do_not_retry_same_args":
        return "do_not_retry_same_args"
    if error_class == "retryable_later":
        return "retryable_later"
    return None


def trail_entry_from_hop(
    hop: Mapping[str, Any],
    *,
    seq: int,
    empty: bool = False,
) -> dict[str, Any]:
    ok = bool(hop.get("ok"))
    status = int(hop.get("status") or hop.get("status_code") or 0)
    err = hop.get("error")
    klass = error_class_for(ok=ok, status=status, error=str(err) if err else None)
    verb = str(hop.get("name") or hop.get("verb") or "")
    entry: dict[str, Any] = {
        "seq": seq,
        "verb": verb,
        "l0": f"zeus.{verb}" if verb else "",
        "ok": ok,
        "http_status": status or None,
        "req_id": hop.get("req_id"),
        "error_class": klass,
        "hint": _hint(ok=ok, status=status, empty=empty, error_class=klass),
        "path": hop.get("url") or hop.get("path") or "",
    }
    return {k: v for k, v in entry.items() if v is not None and v != ""}


def render_trail_inject(entries: Sequence[Mapping[str, Any]], *, max_entries: int = 16) -> str:
    rows = list(entries)[: max(0, int(max_entries))]
    if not rows:
        return ""
    lines = [TRAIL_HEADING]
    for e in rows:
        bits = [f"{e.get('seq', '?')}.", str(e.get("l0") or e.get("verb") or "hop")]
        bits.append("ok" if e.get("ok") else "fail")
        if e.get("req_id"):
            bits.append(f"req_id={e['req_id']}")
        if e.get("error_class"):
            bits.append(e["error_class"])
        if e.get("hint"):
            bits.append(f"hint={e['hint']}")
        lines.append(" ".join(bits))
    return "\n".join(lines)


def upsert_trail_on_system(messages: list[dict[str, Any]], snippet: str) -> None:
    """Splices trail into the system message (Bag B). Never touches the user text."""
    if not snippet or not messages:
        return
    sys = messages[0]
    if not isinstance(sys, dict) or sys.get("role") != "system":
        return
    content = str(sys.get("content") or "")
    if TRAIL_HEADING in content:
        head, _sep, _rest = content.partition(TRAIL_HEADING)
        # drop previous trail block through end (trail is last inject)
        sys["content"] = head.rstrip() + "\n\n" + snippet
    else:
        sys["content"] = content.rstrip() + "\n\n" + snippet
