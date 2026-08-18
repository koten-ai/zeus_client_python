"""Client-true Prompt checklist (authoritative on external path)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.application.detective.extract import (
    catalog_flags_of,
    system_prompt_of,
)

__all__ = ["build_prompt_checklist"]


def _item(
    *,
    id: str,
    label: str,
    status: str,
    group: str,
    detail: str | None = None,
    fix_hint: str | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": id,
        "label": label,
        "status": status,
        "group": group,
    }
    if detail:
        d["detail"] = detail
    if fix_hint:
        d["fix_hint"] = fix_hint
    return d


def build_prompt_checklist(
    *,
    messages: Sequence[Mapping[str, Any]] | None = None,
    system_prompt: str | None = None,
    catalog: Mapping[str, Any] | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    system = system_prompt_of(messages=messages, system_prompt=system_prompt, catalog=catalog)
    flags = catalog_flags_of(system=system, catalog=catalog)
    items: list[dict[str, Any]] = []

    if not system.strip():
        items.append(
            _item(
                id="system_present",
                label="System message present",
                status="fail",
                group="prompt",
                detail="No system message on turn",
                fix_hint="Load catalog / inject system before agent turn",
            )
        )
    else:
        items.append(
            _item(
                id="system_present",
                label="System message present",
                status="pass",
                group="prompt",
                detail=f"chars={len(system)}",
            )
        )

    scope_st = "pass" if flags["has_scope_brief"] else "fail"
    items.append(
        _item(
            id="scope_brief",
            label="SCOPE BRIEF injected",
            status=scope_st,
            group="inject",
            detail="marker ## SCOPE BRIEF" if flags["has_scope_brief"] else "marker missing",
            fix_hint=None if flags["has_scope_brief"] else "merge_scope_brief / borrow live brief",
        )
    )
    mini_st = "pass" if flags["has_mini_schema"] else "fail"
    items.append(
        _item(
            id="mini_schema",
            label="MINI-SCHEMA injected",
            status=mini_st,
            group="inject",
            detail="marker ## MINI-SCHEMA" if flags["has_mini_schema"] else "marker missing",
            fix_hint=None if flags["has_mini_schema"] else "ensure mini-schema in catalog brief",
        )
    )

    tool_n = len(list(tools or ()))
    if tool_n == 0 and isinstance(catalog, Mapping):
        cr_tools = catalog.get("tools")
        if isinstance(cr_tools, list) and cr_tools:
            tool_n = len(cr_tools)
        else:
            cr_verbs = catalog.get("verbs")
            if isinstance(cr_verbs, list):
                tool_n = len(cr_verbs)
    items.append(
        _item(
            id="tools_present",
            label="Tools available to LLM",
            status="pass" if tool_n > 0 else "warn",
            group="tools",
            detail=f"count={tool_n}",
        )
    )

    statuses = [i["status"] for i in items]
    if "fail" in statuses:
        verdict = "fail"
    elif "warn" in statuses:
        verdict = "warn"
    else:
        verdict = "pass"

    summary_bits = []
    if flags["has_scope_brief"] and flags["has_mini_schema"]:
        summary_bits.append("inject OK")
    else:
        missing = []
        if not flags["has_scope_brief"]:
            missing.append("SCOPE BRIEF")
        if not flags["has_mini_schema"]:
            missing.append("MINI-SCHEMA")
        summary_bits.append("missing " + ", ".join(missing))
    summary_bits.append(f"tools={tool_n}")

    return {
        "verdict": verdict,
        "summary": "; ".join(summary_bits),
        "items": items,
        "inject": {
            "has_scope_brief": flags["has_scope_brief"],
            "has_mini_schema": flags["has_mini_schema"],
            "mini_entity_types": list(flags.get("mini_entity_types") or []),
            "brief_sha12": flags.get("brief_sha12"),
            "mini_sha12": flags.get("mini_sha12"),
            "brief_preview": flags.get("brief_preview"),
            "mini_preview": flags.get("mini_preview"),
            "system_chars": len(system),
        },
        "notes": [],
    }
