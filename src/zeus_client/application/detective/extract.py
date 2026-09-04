"""Shared extract helpers for Detective projector (pure, no I/O)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.application.projectors.session_trace import select_primary_req_id

__all__ = [
    "sha12",
    "slice_block",
    "collect_req_ids",
    "preferred_req_id",
    "count_tool_errors",
    "count_rows_signal",
    "system_prompt_of",
    "catalog_flags_of",
    "inject_for_session_trace",
    "inject_slice_sha12s",
    "catalog_for_session_trace",
    "terminate_for_session_trace",
    "notes_blob",
    "hop_error_blob",
    "tool_payload_shape",
]

# Cap returned markdown on rewind (~96 KiB). Matches Hub inject_inspect.go.
INJECT_SECTION_MAX_BYTES = 96 << 10
_PREVIEW_MAX = 400


def _extract_markdown_section(text: str, heading_prefix: str) -> str:
    """Pull ``## HEADING…`` until the next top-level ``## `` or EOF.

    Port of Hub ``extractMarkdownSection`` (inject_inspect.go). ``###`` entity
    headings stay inside MINI-SCHEMA.
    """
    if not text or not heading_prefix:
        return ""
    idx = text.find(heading_prefix)
    if idx < 0:
        return ""
    lines = text[idx:].split("\n")
    kept = [lines[0]]
    for ln in lines[1:]:
        if ln.startswith("## ") and not ln.startswith(heading_prefix):
            break
        kept.append(ln)
    return "\n".join(kept).rstrip("\n")


def slice_block(text: str, kind: str) -> str:
    """Return the marked BRIEF or MINI block (empty if absent).

    Brief stops at ``## MINI-SCHEMA`` or the next H2; mini keeps ``###`` lines.
    Result is stripped so sha12 matches Hub ``sectionFromText``.
    """
    src = text or ""
    if kind == "brief":
        full = _extract_markdown_section(src, "## SCOPE BRIEF")
        if not full:
            return ""
        i = full.find("## MINI-SCHEMA")
        if i > 0:
            full = full[:i].rstrip("\n")
        return full.strip()
    full = _extract_markdown_section(src, "## MINI-SCHEMA")
    return full.strip() if full else ""


def sha12(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def parse_brief_scope_mode(section: str) -> tuple[str, str]:
    """First field after ``scope:`` / ``mode:`` in the brief slice (Hub parity)."""
    scope_line = ""
    mode_line = ""
    for ln in (section or "").split("\n"):
        t = ln.strip()
        low = t.lower()
        if low.startswith("scope:"):
            rest = t[len("scope:") :].strip()
            fields = rest.split()
            if fields:
                scope_line = fields[0]
            if scope_line == "(unscoped)":
                scope_line = ""
        if low.startswith("mode:"):
            rest = t[len("mode:") :].strip()
            fields = rest.split()
            if fields:
                mode_line = fields[0]
    return scope_line, mode_line


def parse_mini_entity_types(section: str) -> list[str]:
    """``### Name`` / ``### Name (fields: N)`` → first token before space or ``(``."""
    out: list[str] = []
    seen: set[str] = set()
    for ln in (section or "").split("\n"):
        t = ln.strip()
        if not t.startswith("### "):
            continue
        rest = t[4:].strip()
        name = rest
        cut = -1
        for i, ch in enumerate(rest):
            if ch in " \t(":
                cut = i
                break
        if cut > 0:
            name = rest[:cut]
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _cap_section_text(text: str, max_bytes: int | None = None) -> tuple[str, bool]:
    cap = INJECT_SECTION_MAX_BYTES if max_bytes is None else max_bytes
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text, False
    clipped = raw[:cap].decode("utf-8", errors="ignore")
    return clipped + "\n…[truncated]", True


def _inject_section(slice_text: str, *, kind: str, include_text: bool) -> dict[str, Any]:
    text = (slice_text or "").strip()
    if not text:
        return {"present": False, "chars": 0}
    out: dict[str, Any] = {
        "present": True,
        "chars": _utf8_len(text),
        "sha12": sha12(text),
        "preview": text[:_PREVIEW_MAX],
    }
    if kind == "brief":
        scope_line, mode_line = parse_brief_scope_mode(text)
        if scope_line:
            out["scope_line"] = scope_line
        if mode_line:
            out["mode_line"] = mode_line
    elif kind == "mini":
        types = parse_mini_entity_types(text)
        if types:
            out["entity_types"] = types
    if include_text:
        capped, truncated = _cap_section_text(text)
        out["text"] = capped
        if truncated:
            out["truncated"] = True
    return out


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
    brief_slice = slice_block(system, "brief")
    mini_slice = slice_block(system, "mini")
    return {
        "has_scope_brief": has_scope,
        "has_mini_schema": has_mini,
        "mini_entity_types": mini_types,
        "brief_sha12": sha12(brief_slice) if has_scope else None,
        "mini_sha12": sha12(mini_slice) if has_mini else None,
        "brief_preview": (brief_slice[:400] if brief_slice else None),
        "mini_preview": (mini_slice[:400] if mini_slice else None),
    }


def inject_for_session_trace(
    *,
    system: str = "",
    catalog: Mapping[str, Any] | None = None,
    source: str | None = None,
    rewind: bool = False,
) -> dict[str, Any]:
    """Hub-shaped ``zeus_response.inject`` / ``public_trace.inject``.

    Parses SCOPE BRIEF / MINI-SCHEMA **slices** from the system prompt actually
    sent to the LLM. Entity types come from ``###`` headings in the mini text,
    never ``catalog.mini_entity_types``. Slim omits ``text``; rewind includes
    full slice text capped at ``INJECT_SECTION_MAX_BYTES``.
    """
    del catalog  # Hub bag is slice-only; do not read catalog.mini_entity_types.
    sys = system or ""
    include_text = bool(rewind)
    return {
        "source": source or "client_llm",
        "system_chars": _utf8_len(sys),
        "scope_brief": _inject_section(
            slice_block(sys, "brief"), kind="brief", include_text=include_text
        ),
        "mini_schema": _inject_section(
            slice_block(sys, "mini"), kind="mini", include_text=include_text
        ),
    }


def inject_slice_sha12s(bag: Mapping[str, Any] | None) -> tuple[str, str]:
    """``(brief_sha12, mini_sha12)`` from a Hub inject bag; empty when absent."""
    inj = bag or {}
    brief = inj.get("scope_brief") if isinstance(inj.get("scope_brief"), Mapping) else {}
    mini = inj.get("mini_schema") if isinstance(inj.get("mini_schema"), Mapping) else {}
    return str(brief.get("sha12") or ""), str(mini.get("sha12") or "")


def _tool_names_ordered(tools: Sequence[Mapping[str, Any]] | None) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for t in tools or ():
        if not isinstance(t, Mapping):
            continue
        fn = t.get("function") if isinstance(t.get("function"), Mapping) else t
        name = str(fn.get("name") or "") if isinstance(fn, Mapping) else ""
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def catalog_for_session_trace(
    *,
    tools: Sequence[Mapping[str, Any]] | None = None,
    chat_request: Mapping[str, Any] | None = None,
    base_id: str | None = None,
    contract_id: str | None = None,
    contract_hash: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Hub join ``zeus_response.catalog`` — names given to the LLM, unique order."""
    names = _tool_names_ordered(tools)
    cr = chat_request if isinstance(chat_request, Mapping) else {}
    if not names and cr:
        cr_tools = cr.get("tools")
        if isinstance(cr_tools, list):
            names = _tool_names_ordered([t for t in cr_tools if isinstance(t, Mapping)])
        if not names:
            cr_verbs = cr.get("verbs")
            if isinstance(cr_verbs, list):
                names = _tool_names_ordered([t for t in cr_verbs if isinstance(t, Mapping)])
    seen = set(names)
    lineage = cr.get("_lineage") if isinstance(cr.get("_lineage"), Mapping) else {}
    bid = base_id or lineage.get("base_id")
    custom_id = lineage.get("custom_id")
    out: dict[str, Any] = {
        "tool_count": len(names),
        "tool_names": names,
        "has_return_verb": "return" in seen or "return_result" in seen,
        "has_pipeline_verb": "pipeline" in seen,
    }
    if bid:
        out["base_id"] = str(bid)
    if custom_id:
        out["custom_label"] = f"custom {{{custom_id}}}"
    elif scope:
        out["custom_label"] = f"custom {{{scope}}}"
    if contract_id:
        out["contract_id"] = str(contract_id)
    if contract_hash:
        out["contract_hash"] = str(contract_hash)
    return out


def hub_terminate_via(via: str | None, *, exit_kind: str | None = None) -> str:
    """Map client terminate tags to Hub join vocabulary."""
    if (exit_kind or "") == "cheap_final":
        return "cheap_final"
    v = (via or "").strip()
    if v in {"return", "return_result"}:
        return "return"
    if v in {"pipeline", "pipeline_turn_complete"}:
        return "pipeline"
    if v == "cheap_final":
        return "cheap_final"
    if v == "client_terminate":
        return "client_terminate"
    return v or "client_terminate"


def terminate_for_session_trace(
    *,
    terminate_via: str | None = None,
    exit_kind: str | None = None,
    ai_process_result: bool = False,
    layer_parsed: bool = False,
) -> dict[str, Any]:
    """Hub join ``zeus_response.terminate`` flags."""
    via = hub_terminate_via(terminate_via, exit_kind=exit_kind)
    cheap = via == "cheap_final"
    has = bool(layer_parsed) or via in {"return", "pipeline", "cheap_final"}
    return {
        "has_terminate": has,
        "terminate_via": via,
        "ai_process_result": bool(ai_process_result),
        "cheap_final": cheap,
    }


def notes_blob(notes: Sequence[str] | None) -> str:
    return "\n".join(str(n) for n in (notes or ()))


def tool_payload_shape(body: Any) -> dict[str, Any]:
    """TRACE-safe tool JSON shape — keys / sizes, not bodies."""
    if body is None:
        return {"bytes": 0, "row_count": 0, "keys": []}
    if isinstance(body, Mapping):
        keys = [str(k) for k in list(body.keys())[:24]]
        raw = str(body)
        sz = None
        result = body.get("result") if isinstance(body.get("result"), Mapping) else None
        if result is not None:
            if isinstance(result.get("items"), list):
                sz = len(result["items"])
            elif isinstance(result.get("node_ids"), list):
                sz = len(result["node_ids"])
            elif result.get("returned_count") is not None:
                try:
                    sz = int(result["returned_count"])
                except (TypeError, ValueError):
                    sz = None
        return {
            "keys": keys,
            "bytes": len(raw),
            "row_count": sz if sz is not None else 0,
        }
    text = str(body)
    return {"bytes": len(text), "row_count": 0, "keys": []}


def hop_error_blob(hops: Sequence[Mapping[str, Any]] | None) -> str:
    parts: list[str] = []
    for h in hops or ():
        if not isinstance(h, Mapping):
            continue
        st = h.get("status")
        if h.get("ok") is False or (isinstance(st, int) and st >= 400):
            parts.append(str(h.get("snippet") or h.get("error") or ""))
    return "\n".join(parts)
