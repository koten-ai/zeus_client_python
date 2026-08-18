"""Diagnosis grades + playbooks + support pack."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from zeus_client.application.detective.extract import (
    collect_req_ids,
    count_rows_signal,
    count_tool_errors,
    preferred_req_id,
)
from zeus_client.application.detective.playbooks import run_playbooks
from zeus_client.application.detective.support_pack import build_support_pack

__all__ = ["build_diagnosis"]


def _grade_from_prompt(verdict: str) -> str:
    return verdict if verdict in ("pass", "warn", "fail", "skip") else "n/a"


def _error_grade(err_n: int) -> str:
    if err_n <= 0:
        return "pass"
    if err_n == 1:
        return "warn"
    return "fail"


def _output_grade(answer: str, rows: int, err_n: int) -> str:
    if err_n > 0 and not (answer or "").strip():
        return "fail"
    if (answer or "").strip() and rows == 0 and err_n == 0:
        return "warn"
    if (answer or "").strip():
        return "pass"
    return "warn"


def _pipeline_grade(hops: Sequence[Mapping[str, Any]]) -> str:
    pipes = [h for h in hops if isinstance(h, Mapping) and h.get("name") == "pipeline"]
    if not pipes:
        return "n/a"
    if any(
        h.get("ok") is False or (isinstance(h.get("status"), int) and h["status"] >= 400)
        for h in pipes
    ):
        return "fail"
    return "pass"


def _speed_grade(total_ms: int | None, rounds: int) -> str:
    if total_ms is None:
        return "n/a"
    if total_ms > 30_000 or rounds > 6:
        return "warn"
    if total_ms > 90_000:
        return "fail"
    return "pass"


def build_diagnosis(
    *,
    answer: str = "",
    hops: Sequence[Mapping[str, Any]] | None = None,
    notes: Sequence[str] | None = None,
    prompt: Mapping[str, Any] | None = None,
    contract_status: str | None = None,
    layer_a: Mapping[str, Any] | None = None,
    turn_id: str = "",
    chat_id: str = "",
    session_id: str = "",
    status: str = "",
    total_ms: int | None = None,
    rounds: int = 0,
    target: Mapping[str, Any] | None = None,
    zeus_url: str | None = None,
    client_version: str = "",
    catalog: Mapping[str, Any] | None = None,
    tokens: Mapping[str, Any] | None = None,
    export_ref: str | None = None,
) -> dict[str, Any]:
    hops = list(hops or ())
    prompt = dict(prompt or {})
    err_n = count_tool_errors(hops)
    rows = count_rows_signal(hops)
    prompt_grade = _grade_from_prompt(str(prompt.get("verdict") or "n/a"))
    error_grade = _error_grade(err_n)
    output_grade = _output_grade(answer, rows, err_n)
    pipeline_grade = _pipeline_grade(hops)
    speed_grade = _speed_grade(total_ms, rounds)

    playbooks = run_playbooks(
        hops=hops,
        notes=notes,
        answer=answer,
        prompt=prompt,
        contract_status=contract_status,
        layer_a=layer_a,
    )

    if playbooks:
        headline = str(
            playbooks[0].get("summary") or playbooks[0].get("title") or "Issues detected"
        )
    elif prompt_grade == "pass" and error_grade == "pass":
        headline = "Turn looks healthy"
    else:
        headline = "Review prompt / tool grades"

    pref = preferred_req_id(hops)
    req_ids = collect_req_ids(hops)
    support = build_support_pack(
        headline=headline,
        turn_id=turn_id,
        chat_id=chat_id,
        session_id=session_id,
        preferred_req_id=pref,
        req_ids=req_ids,
        hops=hops,
        playbooks=playbooks,
        prompt_verdict=prompt_grade,
        notes=notes,
        status=status,
        target=target,
        zeus_url=zeus_url,
        client_version=client_version,
        catalog=catalog,
        contract_status=contract_status,
        inject=prompt.get("inject") if isinstance(prompt.get("inject"), Mapping) else None,
        layer_a=layer_a,
        tokens=tokens,
        export_ref=export_ref,
    )

    return {
        "headline": headline,
        "prompt_grade": prompt_grade,
        "speed_grade": speed_grade,
        "error_grade": error_grade,
        "output_grade": output_grade,
        "pipeline_grade": pipeline_grade,
        "prompt": {
            "verdict": prompt.get("verdict"),
            "summary": prompt.get("summary"),
        },
        "slow": {"total_ms": total_ms, "rounds": rounds, "grade": speed_grade},
        "errors": {"count": err_n, "grade": error_grade},
        "output": {"rows_signal": rows, "answer_chars": len(answer or ""), "grade": output_grade},
        "pipeline": {"grade": pipeline_grade},
        "playbooks": playbooks,
        "support_pack": support,
    }
