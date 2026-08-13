"""Small client_v1 Detective playbook set (not full Hub catalogue)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.application.detective.extract import (
    count_rows_signal,
    count_tool_errors,
    hop_error_blob,
    notes_blob,
)

__all__ = ["PLAYBOOK_IDS", "run_playbooks"]

PLAYBOOK_IDS = (
    "boundary_collections",
    "missing_inject",
    "hybrid_empty_find_ok",
    "project_dotted_fk",
    "tool_errors",
    "hollow_answer",
    "contract_drift",
)


def _pb(
    id: str,
    title: str,
    severity: str,
    summary: str,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "severity": severity,
        "summary": summary,
        "actions": list(actions or []),
    }


def run_playbooks(
    *,
    hops: Sequence[Mapping[str, Any]] | None = None,
    notes: Sequence[str] | None = None,
    answer: str = "",
    prompt: Mapping[str, Any] | None = None,
    contract_status: str | None = None,
    layer_a: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    hops = list(hops or ())
    notes_s = notes_blob(notes)
    err_blob = hop_error_blob(hops) + "\n" + notes_s
    out: list[dict[str, Any]] = []

    if re.search(r"unknown boundary:\s*[\"']?collections", err_blob, re.I):
        out.append(
            _pb(
                "boundary_collections",
                "Boundary collections not registered",
                "high",
                "Tool error mentions unknown boundary collections — register N1QL/boundary then restart zeus-api.",
                [
                    "Check Zeus boundary/collections registration",
                    "Never unregister prod boundary casually",
                ],
            )
        )

    inj = (prompt or {}).get("inject") if isinstance(prompt, Mapping) else {}
    inj = inj if isinstance(inj, Mapping) else {}
    if not inj.get("has_scope_brief") or not inj.get("has_mini_schema"):
        out.append(
            _pb(
                "missing_inject",
                "SCOPE BRIEF / MINI-SCHEMA missing on client path",
                "high",
                "Client system prompt lacks inject markers required for floor-5 control plane.",
                [
                    "Verify catalog load + merge_scope_brief",
                    "Do not trust Hub tool-hop inject tiles for external agents",
                ],
            )
        )

    # hybrid empty + later find with data
    names = [str(h.get("name") or "") for h in hops if isinstance(h, Mapping)]
    if any(n in ("search", "hybrid") for n in names) and any(
        n in ("find", "project") for n in names
    ):
        search_empty = False
        find_ok = False
        for h in hops:
            if not isinstance(h, Mapping):
                continue
            n = str(h.get("name") or "")
            snip = str(h.get("snippet") or "")
            if n in ("search", "hybrid") and (
                "[]" in snip or "empty" in snip.lower() or h.get("ok") is False
            ):
                search_empty = True
            if n in ("find", "project") and h.get("ok") is not False and snip.strip():
                find_ok = True
        if search_empty and find_ok:
            out.append(
                _pb(
                    "hybrid_empty_find_ok",
                    "Search empty but find/project returned data",
                    "med",
                    "FTS/hybrid empty while graph find later succeeded — common ID/strategy mismatch.",
                    [
                        "Prefer FTS typeahead for dropdowns",
                        "Do not treat empty hybrid as hard fail",
                    ],
                )
            )

    if re.search(r"unknown FK|attributes\.\w+|dotted", err_blob, re.I):
        out.append(
            _pb(
                "project_dotted_fk",
                "Project dotted FK / attributes path",
                "med",
                "Tool error suggests dotted attribute or FK projection issue.",
                [
                    "Check project fields vs entity schema",
                    "Avoid projecting FTS biz: keys as graph ids",
                ],
            )
        )

    err_n = count_tool_errors(hops)
    if err_n > 0 and not any(p["id"] == "boundary_collections" for p in out):
        out.append(
            _pb(
                "tool_errors",
                f"{err_n} tool hop error(s)",
                "med" if err_n < 3 else "high",
                "One or more Zeus hops returned 4xx/5xx or ok=false.",
                ["Open preferred_req_id in Hub Detective", "Inspect hop snippets on debug.hops"],
            )
        )

    rows = count_rows_signal(hops)
    conf = (layer_a or {}).get("confidence") if isinstance(layer_a, Mapping) else None
    ans = (answer or "").strip()
    if ans and rows == 0 and err_n == 0 and len(hops) > 0:
        sev = "med"
        if conf in ("high", "med"):
            sev = "high"
        out.append(
            _pb(
                "hollow_answer",
                "Prose answer without row evidence",
                sev,
                "Model produced an answer but hops show no clear row/items payload.",
                ["Verify tool result unpacking", "Check cheap vs insight path"],
            )
        )

    cs = (contract_status or "").lower()
    if cs in ("drift", "mismatch", "fail", "failed"):
        out.append(
            _pb(
                "contract_drift",
                "Contract drift / mismatch",
                "high",
                f"contract_status={contract_status}",
                [
                    "Align scope_contracts hash with Verify stamp",
                    "Never invent production contract_hash",
                ],
            )
        )

    return out
