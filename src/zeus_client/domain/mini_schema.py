"""Parse ## MINI-SCHEMA from a stamped chat_request (hash-excluded inject)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "MISSING_MINI_SCHEMA",
    "system_prompt_text",
    "get_mini_schema",
    "classify_mini_schema",
]

MISSING_MINI_SCHEMA = "missing_mini_schema"

_MINI_HEADER_RE = re.compile(r"^###\s+(?P<ent>.+?)\s+\(fields:\s*(?P<n>\d+)\)\s*$")
_MINI_FIELD_RE = re.compile(
    r"^\s+-\s+(?P<path>\S+)\s+(?P<kind>\S+)\s+\[(?P<idx>[^\]]+)\]"
    r"(?:\s+(?P<trailer>.*\S))?\s*$"
)
_MINI_INVERSE_RE = re.compile(
    r"^\s+\u2190\s+(?P<token>\S+)\s+\((?P<kind>[^)]+)\)\s+--\s+(?P<recipe>.*\S)?\s*$"
)
_FK_TO_RE = re.compile(r"fk_to=(\S+)")
_VIA_RE = re.compile(r"via=(\S+)")
_EX_RE = re.compile(r"ex:\s*(.+)$")
_NON_FILTERABLE_KINDS = {"display", "text_fts"}


def system_prompt_text(chat_req: Mapping[str, Any] | None) -> str:
    """Prefer messages[0].content; fall back to instructions.system_prompt."""
    if not isinstance(chat_req, Mapping):
        return ""
    content = ""
    try:
        messages = chat_req.get("messages") or []
        if messages and isinstance(messages[0], Mapping):
            content = str(messages[0].get("content") or "")
    except Exception:
        content = ""
    if "## MINI-SCHEMA" not in content and "## SCOPE BRIEF" not in content:
        instr = chat_req.get("instructions") or {}
        if isinstance(instr, dict):
            sp = instr.get("system_prompt") or ""
            if "## MINI-SCHEMA" in sp or "## SCOPE BRIEF" in sp:
                return str(sp)
    return content


def get_mini_schema(chat_req: Mapping[str, Any] | str | Path, *, values: bool = False) -> dict:
    """Structured MINI-SCHEMA. Empty entity_types when the brief is absent."""
    if isinstance(chat_req, (str, Path)):
        chat_req = json.loads(Path(chat_req).read_text(encoding="utf-8"))
    if not isinstance(chat_req, Mapping):
        return {"scope": "", "mode": "", "entity_types": {}}

    out: dict[str, Any] = {"scope": "", "mode": "", "entity_types": {}}
    content = system_prompt_text(chat_req)
    if not content:
        return out

    m = re.search(r"^scope:\s+(\S+)", content, re.MULTILINE)
    if m:
        out["scope"] = m.group(1)
    m = re.search(r"^mode:\s+(\S+)", content, re.MULTILINE)
    if m:
        out["mode"] = m.group(1)

    start = content.find("## MINI-SCHEMA")
    if start < 0:
        return out
    rest = content[start:]
    nxt = re.search(r"\n##\s+(?!MINI-SCHEMA)", rest)
    block = rest[: nxt.start()] if nxt else rest

    cur = None
    in_inverse = False
    for line in block.splitlines():
        hm = _MINI_HEADER_RE.match(line)
        if hm:
            cur = hm.group("ent")
            out["entity_types"][cur] = {
                "field_count": int(hm.group("n")),
                "fields": {},
                "inverse_fks": [],
            }
            in_inverse = False
            continue
        if cur is None:
            continue
        if line.strip() == "inverse_fks:":
            in_inverse = True
            continue
        if in_inverse:
            im = _MINI_INVERSE_RE.match(line)
            if im:
                ent, _, path = im.group("token").partition(".")
                out["entity_types"][cur]["inverse_fks"].append(
                    {
                        "from_entity": ent,
                        "from_path": path,
                        "kind": im.group("kind"),
                    }
                )
            continue
        fm = _MINI_FIELD_RE.match(line)
        if not fm:
            continue
        kind = fm.group("kind")
        idx = fm.group("idx")
        field: dict[str, Any] = {
            "kind": kind,
            "indexed": idx,
            "filterable": kind not in _NON_FILTERABLE_KINDS and idx not in ("none", ""),
        }
        trailer = fm.group("trailer") or ""
        fk = _FK_TO_RE.search(trailer)
        if fk:
            field["fk_to"] = fk.group(1)
        via = _VIA_RE.search(trailer)
        if via:
            field["via"] = via.group(1)
        if trailer.lstrip().startswith("--"):
            field["note"] = trailer.lstrip()[2:].strip()
        if values:
            ex = _EX_RE.search(trailer)
            if ex:
                field["examples"] = [e.strip() for e in ex.group(1).split(",") if e.strip()]
        out["entity_types"][cur]["fields"][fm.group("path")] = field
    return out


def classify_mini_schema(parsed: Mapping[str, Any] | None) -> dict[str, Any]:
    """Stable ``error_class`` for missing MINI-SCHEMA (CHECKLIST E fail_client tape)."""
    entities = parsed.get("entity_types") if isinstance(parsed, Mapping) else None
    present = isinstance(entities, dict) and bool(entities)
    out: dict[str, Any] = dict(parsed) if isinstance(parsed, Mapping) else {"entity_types": {}}
    out["result"] = present
    out["error_class"] = None if present else MISSING_MINI_SCHEMA
    return out
