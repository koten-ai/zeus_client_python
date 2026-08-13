"""Legacy-shaped public_trace dict for widgets (projector over turn debug)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["build_public_trace"]


def build_public_trace(
    *,
    turn_id: str,
    answer: str,
    status: str,
    rounds: int,
    notes: Sequence[str],
    hops: Sequence[Mapping[str, Any]],
    ai_process_result: bool,
    ai_process_result_exit: str | None,
    layer_a: Mapping[str, Any] | None,
    policy: str | None,
    flags: Mapping[str, bool] | None,
    steps: Sequence[Mapping[str, Any]] | None = None,
    tokens: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Widget-friendly projection — never put G2 dumps in answer field."""
    out: dict[str, Any] = {
        "turn_id": turn_id,
        "answer": answer,
        "status": status,
        "rounds": rounds,
        "notes": list(notes),
        "steps": list(steps or ()),
        "hops": [dict(h) for h in hops],
        "ai_process_result": ai_process_result,
        "ai_process_result_exit": ai_process_result_exit,
        "layer_a": dict(layer_a) if layer_a else None,
        "policy": policy,
        "flags": dict(flags or {}),
        # G2 quarantine: scores stay under artifacts key only when present on layer_a
        "artifacts_keys": (
            ["jail_break_attempt", "wish_i_knew", "hooks_jailbreak_score"]
            if layer_a
            else []
        ),
    }
    if tokens is not None:
        out["tokens"] = dict(tokens)
    return out
