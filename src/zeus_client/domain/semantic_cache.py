"""Semantic agent cache — inject, write policy, deny rules (ZF-WISH-001).

Pure domain: no HTTP. Zeus embeds/stores; the client only decides *whether*
to recall/write and how recalled blocks become bag B text.

Not the Zeus tool ``agent_memory.read`` (principal find_nodes).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.security.redact import REDACTED, default_redactor

__all__ = [
    "BLOCK_TYPES",
    "DEFAULT_INJECT_KEY",
    "DEFAULT_APPLY_TO_MODES",
    "heading_for",
    "normalize_block_type",
    "ttl_seconds_from",
    "should_recall",
    "should_write_auto",
    "block_text_denied_reason",
    "prepare_write_text",
    "render_semantic_memory_inject",
    "upsert_semantic_memory_on_system",
]

BLOCK_TYPES: tuple[str, ...] = ("conversational", "profile", "semantic")
DEFAULT_INJECT_KEY = "semantic_memory"
DEFAULT_APPLY_TO_MODES: tuple[str, ...] = ("agent",)

_SYSTEM_DUMP_MARKERS = (
    "## SCOPE BRIEF",
    "## MINI-SCHEMA",
    "## Company context",
    "## Rules",
    "## Output request",
    "ZEUS_TOOL_TRAIL",
)
_G2_MARKERS = (
    "wish_i_knew",
    "jail_break_attempt",
    "hooks_jailbreak_score",
    "subject_confidence",
)
_SECRETS_RE = re.compile(
    r"(?i)(\bauthorization\s*:|\bbearer\s+\S+|\bbasic\s+\S+|"
    r"\b(api[_-]?key|secret[_-]?key|password|passwd)\s*[:=]|"
    r"\b(sk-|xai-)[a-z0-9\-_]{8,})"
)


def heading_for(key: str | None) -> str:
    name = (key or DEFAULT_INJECT_KEY).strip() or DEFAULT_INJECT_KEY
    return f"{name}:"


def normalize_block_type(raw: str | None) -> str:
    t = (raw or "").strip().lower()
    if t in BLOCK_TYPES:
        return t
    return "conversational"


def ttl_seconds_from(raw: Any, *, default: int = 604800) -> int:
    """Accept a single int or a per-type map (conversational key)."""
    if raw is None:
        return int(default)
    if isinstance(raw, Mapping):
        for key in ("conversational", "default", "profile", "semantic"):
            if key in raw and raw[key] is not None:
                try:
                    return max(0, int(raw[key]))
                except (TypeError, ValueError):
                    continue
        return int(default)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return int(default)


def _master_on(cfg: Any) -> bool:
    return bool(getattr(cfg, "enabled", False))


def _mode_allowed(cfg: Any, mode: str) -> bool:
    modes = tuple(getattr(cfg, "apply_to_modes", DEFAULT_APPLY_TO_MODES) or DEFAULT_APPLY_TO_MODES)
    m = (mode or "agent").strip().lower() or "agent"
    return m in {str(x).strip().lower() for x in modes}


def should_recall(cfg: Any, message: str, *, mode: str = "agent") -> tuple[bool, str]:
    """Return (ok, skip_reason). skip_reason is empty when recall should run."""
    if not _master_on(cfg):
        return False, "disabled"
    if not _mode_allowed(cfg, mode):
        return False, "mode"
    recall = getattr(cfg, "recall", None)
    if recall is not None and not bool(getattr(recall, "enabled", True)):
        return False, "recall_disabled"
    min_chars = int(getattr(recall, "min_query_chars", 12) if recall is not None else 12)
    if len((message or "").strip()) < min_chars:
        return False, "min_query_chars"
    return True, ""


def should_write_auto(cfg: Any, *, mode: str = "agent") -> tuple[bool, str]:
    """Auto write after commit (not explicit API)."""
    if not _master_on(cfg):
        return False, "disabled"
    if not _mode_allowed(cfg, mode):
        return False, "mode"
    write = getattr(cfg, "write", None)
    if write is None:
        return False, "write_disabled"
    if not bool(getattr(write, "enabled", True)):
        return False, "write_disabled"
    if not bool(getattr(write, "on_turn_commit", True)):
        return False, "on_turn_commit"
    if bool(getattr(write, "write_explicit_only", True)):
        return False, "write_explicit_only"
    return True, ""


def block_text_denied_reason(text: str, cfg: Any | None = None) -> str | None:
    """Why this text must not be stored. None = allowed (length still checked by caller)."""
    body = text or ""
    if _SECRETS_RE.search(body):
        return "secrets"
    upper = body
    for marker in _SYSTEM_DUMP_MARKERS:
        if marker in upper:
            return "system_dump"
    lowered = body.lower()
    for marker in _G2_MARKERS:
        if marker in lowered:
            return "g2"
    privacy = getattr(cfg, "privacy", None) if cfg is not None else None
    patterns = tuple(getattr(privacy, "deny_regex", ()) or ()) if privacy is not None else ()
    for pat in patterns:
        try:
            if re.search(str(pat), body):
                return "deny_regex"
        except re.error:
            continue
    return None


def prepare_write_text(text: str, cfg: Any) -> tuple[str | None, str]:
    """Truncate / optional redact. Returns (payload_or_none, skip_reason)."""
    write = getattr(cfg, "write", None)
    min_chars = int(getattr(write, "min_chars", 24) if write is not None else 24)
    max_chars = int(getattr(write, "max_chars_per_block", 2000) if write is not None else 2000)
    raw = (text or "").strip()
    if len(raw) < min_chars:
        return None, "min_chars"
    privacy = getattr(cfg, "privacy", None)
    if privacy is not None and bool(getattr(privacy, "redact_before_write", False)):
        raw = default_redactor().text(raw, max_chars=-1)
        if REDACTED in raw and len(raw.replace(REDACTED, "").strip()) < min_chars:
            return None, "secrets"
    denied = block_text_denied_reason(raw, cfg)
    if denied:
        return None, denied
    if max_chars > 0 and len(raw) > max_chars:
        raw = raw[:max_chars]
    return raw, ""


def _sort_blocks(
    blocks: Sequence[Mapping[str, Any]],
    *,
    order: str,
) -> list[Mapping[str, Any]]:
    rows = [b for b in blocks if isinstance(b, Mapping)]
    if (order or "score_desc").strip().lower() == "recency":

        def _recency_key(b: Mapping[str, Any]) -> str:
            return str(b.get("created_at") or "")

        return sorted(rows, key=_recency_key, reverse=True)
    return sorted(rows, key=lambda b: float(b.get("score") or 0.0), reverse=True)


def _block_line(block: Mapping[str, Any], include_fields: Sequence[str]) -> str:
    fields = [str(f).strip().lower() for f in include_fields if str(f).strip()]
    if not fields:
        fields = ["summary", "text"]
    body = ""
    for field in fields:
        val = block.get(field)
        if isinstance(val, str) and val.strip():
            body = val.strip()
            break
    if not body:
        return ""
    typ = normalize_block_type(str(block.get("type") or ""))
    return f"[{typ}] {body}"


def render_semantic_memory_inject(
    blocks: Sequence[Mapping[str, Any]],
    *,
    key: str = DEFAULT_INJECT_KEY,
    max_chars: int = 4000,
    max_blocks: int = 5,
    include_fields: Sequence[str] = ("summary", "text"),
    order: str = "score_desc",
) -> str:
    """Deterministic bag B snippet. Empty string if nothing to inject."""
    heading = heading_for(key)
    cap_blocks = max(0, int(max_blocks))
    cap_chars = max(0, int(max_chars))
    if cap_blocks == 0 or cap_chars == 0:
        return ""
    ordered = _sort_blocks(blocks, order=order)[:cap_blocks]
    lines = [heading]
    used = len(heading) + 1
    n = 0
    for block in ordered:
        piece = _block_line(block, include_fields)
        if not piece:
            continue
        n += 1
        row = f"{n}. {piece}"
        extra = len(row) + 1
        if used + extra > cap_chars:
            remain = cap_chars - used - 1
            if remain > 8:
                lines.append(row[:remain].rstrip() + "…")
            break
        lines.append(row)
        used += extra
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def upsert_semantic_memory_on_system(
    messages: list[dict[str, Any]],
    snippet: str,
    *,
    key: str = DEFAULT_INJECT_KEY,
) -> None:
    """Splice inject into the system message (bag B). Never touches user text."""
    if not snippet or not messages:
        return
    sys = messages[0]
    if not isinstance(sys, dict) or sys.get("role") != "system":
        return
    heading = heading_for(key)
    content = str(sys.get("content") or "")
    if heading in content:
        head, _sep, _rest = content.partition(heading)
        sys["content"] = head.rstrip() + "\n\n" + snippet
    else:
        sys["content"] = content.rstrip() + "\n\n" + snippet
