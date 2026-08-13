"""Detective Overview tab (no Ask-AI chat)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from zeus_client_v2.application.detective.extract import (
    catalog_flags_of,
    collect_req_ids,
    preferred_req_id,
    system_prompt_of,
)

__all__ = ["build_overview"]


def _tokens_block(tokens: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(tokens, Mapping) or not tokens:
        return None
    return {
        "prompt": int(tokens.get("prompt") or 0),
        "completion": int(tokens.get("completion") or 0),
        "total": int(tokens.get("total") or 0),
        "cached": int(tokens.get("cached") or 0),
        "extra": int(tokens.get("extra") or 0),
        "ok": bool(tokens.get("ok")),
    }


def build_overview(
    *,
    turn_id: str = "",
    answer: str = "",
    status: str = "",
    rounds: int = 0,
    hops: Sequence[Mapping[str, Any]] | None = None,
    notes: Sequence[str] | None = None,
    messages: Sequence[Mapping[str, Any]] | None = None,
    system_prompt: str | None = None,
    catalog: Mapping[str, Any] | None = None,
    layer_a: Mapping[str, Any] | None = None,
    total_ms: int | None = None,
    hub_base_url: str | None = None,
    session_id: str | None = None,
    target: Mapping[str, Any] | None = None,
    ai_process_result: bool | None = None,
    ai_process_result_exit: str | None = None,
    tokens: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    hops = list(hops or ())
    req_ids = collect_req_ids(hops)
    pref = preferred_req_id(hops)
    system = system_prompt_of(messages=messages, system_prompt=system_prompt, catalog=catalog)
    flags = catalog_flags_of(system=system, catalog=catalog)
    hub = (hub_base_url or "").rstrip("/")
    links: dict[str, str] = {}
    if hub and pref:
        links["req"] = f"{hub}/hub/debug/req/{pref}"
        # Lab Detective often shares hub base; ops still uses /hub/debug/session/{sid}
        links["detective_req"] = f"{hub}/hub/debug/req/{pref}"
    if hub and session_id:
        links["session"] = f"{hub}/hub/debug/session/{session_id}"
    tgt = dict(target or {})
    tok = _tokens_block(tokens)
    return {
        "turn_id": turn_id,
        "status": status,
        "rounds": rounds,
        "total_ms": total_ms,
        "req_ids": list(req_ids),
        "preferred_req_id": pref,
        "hop_count": len(hops),
        "answer_preview": (answer or "")[:240],
        "catalog_flags": {
            "has_scope_brief": flags["has_scope_brief"],
            "has_mini_schema": flags["has_mini_schema"],
        },
        "layer_a_summary": (layer_a or {}).get("summary") if isinstance(layer_a, Mapping) else None,
        "layer_a_confidence": (layer_a or {}).get("confidence") if isinstance(layer_a, Mapping) else None,
        "ai_process_result": ai_process_result,
        "ai_process_result_exit": ai_process_result_exit,
        "hub_links": links,
        "target": {
            "bucket": tgt.get("bucket"),
            "scope": tgt.get("scope"),
            "collection": tgt.get("collection"),
            "mode": tgt.get("mode"),
        },
        "notes_count": len(list(notes or ())),
        "tokens": tok,
    }
