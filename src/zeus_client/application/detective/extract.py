"""Shared extract helpers for Detective projector (pure, no I/O)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.application.projectors.session_trace import select_primary_req_id

__all__ = [
    "sha12",
    "collect_req_ids",
    "preferred_req_id",
    "count_tool_errors",
    "count_rows_signal",
    "system_prompt_of",
    "catalog_flags_of",
    "notes_blob",
    "hop_error_blob",
]


def sha12(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def collect_req_ids(hops: Sequence[Mapping[str, Any]] | None) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for h in hops or ():
        if not isinstance(h, Mapping):
            continue
        rid = h.get("req_id")
        if rid and str(rid) not in seen:
            s = str(rid)
            seen.add(s)
            out.append(s)
    return tuple(out)


def preferred_req_id(hops: Sequence[Mapping[str, Any]] | None) -> str | None:
    try:
        return select_primary_req_id(list(hops or ()))
    except Exception:
        ids = collect_req_ids(hops)
        return ids[-1] if ids else None


def count_tool_errors(
    hops: Sequence[Mapping[str, Any]] | None, steps: Sequence[Mapping[str, Any]] | None = None
) -> int:
    n = 0
    for h in hops or ():
        if not isinstance(h, Mapping):
            continue
        st = h.get("status")
        ok = h.get("ok")
        if ok is False:
            n += 1
            continue
        if isinstance(st, int) and st >= 400:
            n += 1
    for s in steps or ():
        if isinstance(s, Mapping) and s.get("type") == "llm_error":
            n += 1
    return n


def count_rows_signal(hops: Sequence[Mapping[str, Any]] | None) -> int:
    """Best-effort non-empty hop count (snippet / ok)."""
    n = 0
    for h in hops or ():
        if not isinstance(h, Mapping):
            continue
        if h.get("ok") is False:
            continue
        snip = str(h.get("snippet") or "")
        if (
            any(k in snip for k in ('"rows"', '"items"', '"node_ids"', '"src_keys"'))
            or h.get("ok") is True
            and snip.strip()
            and snip.strip() not in ("{}", "null")
        ):
            n += 1
    return n


def system_prompt_of(
    *,
    messages: Sequence[Mapping[str, Any]] | None = None,
    system_prompt: str | None = None,
    catalog: Mapping[str, Any] | None = None,
) -> str:
    if isinstance(system_prompt, str) and system_prompt.strip():
        return system_prompt
    if isinstance(catalog, Mapping):
        sm = catalog.get("system_message")
        if isinstance(sm, str) and sm.strip():
            return sm
    for m in messages or ():
        if isinstance(m, Mapping) and m.get("role") == "system":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                return c
    return ""


def catalog_flags_of(
    *,
    system: str,
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cat = dict(catalog or {})
    has_scope = bool(cat.get("has_scope_brief"))
    has_mini = bool(cat.get("has_mini_schema"))
    if system:
        if not has_scope and re.search(r"(?m)^##\s+SCOPE\s+BRIEF\b", system):
            has_scope = True
        if not has_mini and re.search(r"(?m)^##\s+MINI-SCHEMA\b", system):
            has_mini = True
    mini_types: list[str] = []
    raw_types = cat.get("mini_entity_types")
    if isinstance(raw_types, (list, tuple)):
        mini_types = [str(x) for x in raw_types]
    return {
        "has_scope_brief": has_scope,
        "has_mini_schema": has_mini,
        "mini_entity_types": mini_types,
        "brief_sha12": sha12(system) if has_scope else None,
        "mini_sha12": sha12(system) if has_mini else None,
    }


def notes_blob(notes: Sequence[str] | None) -> str:
    return "\n".join(str(n) for n in (notes or ()))


def hop_error_blob(hops: Sequence[Mapping[str, Any]] | None) -> str:
    parts: list[str] = []
    for h in hops or ():
        if not isinstance(h, Mapping):
            continue
        st = h.get("status")
        if h.get("ok") is False or (isinstance(st, int) and st >= 400):
            parts.append(str(h.get("snippet") or h.get("error") or ""))
    return "\n".join(parts)
