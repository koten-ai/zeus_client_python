"""Build Client Detective briefing (Overview · Diagnosis · Prompt) — pure local.

Kill-switch: ``DebugPolicy.detective_briefing=False`` or env ``ZEUS_CLIENT_DETECTIVE=0``.
Never raise into a successful domain turn — callers soft-fail.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.application.detective.diagnosis import build_diagnosis
from zeus_client.application.detective.hub_hydrate import merge_hub_hydrate
from zeus_client.application.detective.overview import build_overview
from zeus_client.application.detective.prompt_checklist import build_prompt_checklist
from zeus_client.application.tokens import sum_provider_tokens

__all__ = [
    "detective_enabled",
    "build_detective_briefing",
    "safe_build_detective_briefing",
]


def detective_enabled(
    *,
    debug_policy_enabled: bool | None = True,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return False when kill-switch is off."""
    environ = env if env is not None else os.environ
    raw = str(environ.get("ZEUS_CLIENT_DETECTIVE", "1")).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if debug_policy_enabled is False:
        return False
    return True


def build_detective_briefing(
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
    tools: Sequence[Mapping[str, Any]] | None = None,
    layer_a: Mapping[str, Any] | None = None,
    total_ms: int | None = None,
    hub_base_url: str | None = None,
    session_id: str | None = None,
    target: Mapping[str, Any] | None = None,
    contract_status: str | None = None,
    ai_process_result: bool | None = None,
    ai_process_result_exit: str | None = None,
    hub_payload: Mapping[str, Any] | None = None,
    # legacy alias: public_trace dict
    public_trace: Mapping[str, Any] | None = None,
    chat_id: str = "",
    zeus_url: str | None = None,
    client_version: str = "",
    export_ref: str | None = None,
) -> dict[str, Any]:
    """Pure builder — schema v1 keys: version, source, hub_hydrated, overview, prompt, diagnosis."""
    pt = dict(public_trace or {})
    hops = list(hops if hops is not None else pt.get("hops") or ())
    notes = list(notes if notes is not None else pt.get("notes") or ())
    answer = answer if answer else str(pt.get("answer") or "")
    status = status or str(pt.get("status") or "")
    rounds = rounds or int(pt.get("rounds") or 0)
    layer_a = layer_a if layer_a is not None else pt.get("layer_a")  # type: ignore[assignment]
    turn_id = turn_id or str(pt.get("turn_id") or "")
    ai_process_result = (
        ai_process_result if ai_process_result is not None else pt.get("ai_process_result")
    )
    ai_process_result_exit = (
        ai_process_result_exit
        if ai_process_result_exit is not None
        else pt.get("ai_process_result_exit")
    )

    prompt = build_prompt_checklist(
        messages=messages,
        system_prompt=system_prompt,
        catalog=catalog,
        tools=tools,
    )
    # Prefer explicit tokens, else public_trace.tokens, else sum steps on public_trace.
    tokens_arg = None
    if isinstance(pt.get("tokens"), Mapping):
        tokens_arg = pt.get("tokens")
    elif pt.get("steps"):
        tokens_arg = sum_provider_tokens(steps=list(pt.get("steps") or ()))
    overview = build_overview(
        turn_id=turn_id,
        answer=answer,
        status=status,
        rounds=rounds,
        hops=hops,
        notes=notes,
        messages=messages,
        system_prompt=system_prompt,
        catalog=catalog,
        layer_a=layer_a if isinstance(layer_a, Mapping) else None,
        total_ms=total_ms,
        hub_base_url=hub_base_url,
        session_id=session_id,
        target=target,
        ai_process_result=bool(ai_process_result) if ai_process_result is not None else None,
        ai_process_result_exit=str(ai_process_result_exit)
        if ai_process_result_exit is not None
        else None,
        tokens=tokens_arg if isinstance(tokens_arg, Mapping) else None,
    )
    diagnosis = build_diagnosis(
        answer=answer,
        hops=hops,
        notes=notes,
        prompt=prompt,
        contract_status=contract_status,
        layer_a=layer_a if isinstance(layer_a, Mapping) else None,
        turn_id=turn_id,
        chat_id=chat_id,
        session_id=session_id or "",
        status=status,
        total_ms=total_ms,
        rounds=rounds,
        target=target,
        zeus_url=zeus_url,
        client_version=client_version,
        catalog=catalog,
        tokens=tokens_arg if isinstance(tokens_arg, Mapping) else None,
        export_ref=export_ref or turn_id,
    )
    briefing: dict[str, Any] = {
        "version": 1,
        "source": "client",
        "hub_hydrated": False,
        "overview": overview,
        "prompt": prompt,
        "diagnosis": diagnosis,
    }
    if hub_payload is not None:
        briefing = merge_hub_hydrate(
            briefing,
            hub_payload,
            preferred_req_id=overview.get("preferred_req_id"),
        )
    return briefing


def safe_build_detective_briefing(**kwargs: Any) -> dict[str, Any] | None:
    """Soft-fail wrapper — returns None on any builder exception."""
    try:
        enabled = kwargs.pop("enabled", True)
        env = kwargs.pop("env", None)
        if not detective_enabled(debug_policy_enabled=bool(enabled), env=env):
            return None
        return build_detective_briefing(**kwargs)
    except Exception:
        return None
