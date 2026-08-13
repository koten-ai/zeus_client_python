"""Hub-identical provider token rollup (Token IN / OUT / TOT / cached).

Mirrors Zeus Detective provider math (recordAIHop sum + providerTokens):

- IN  = Σ usage.prompt_tokens
- OUT = Σ usage.completion_tokens
- TOT = Σ usage.total_tokens (else IN+OUT; may be > IN+OUT for reasoning extras)
- cached = Σ prompt_tokens_details.cached_tokens or top-level cached_tokens

Never invents billing from payload size. Multi-round = sum, not last hop only.
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

__all__ = [
    "normalize_usage",
    "usage_from_ai_response",
    "sum_provider_tokens",
    "attach_trace_tokens",
]

_LLM_STEP_TYPES = frozenset({"llm", "force_final"})


def _as_int(v: Any) -> int:
    try:
        if v is None:
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def normalize_usage(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Normalize OpenAI-shaped usage to Hub short keys."""
    u = usage if isinstance(usage, Mapping) else {}
    details = u.get("prompt_tokens_details") or {}
    if not isinstance(details, Mapping):
        details = {}
    cached = details.get("cached_tokens", u.get("cached_tokens"))
    return {
        "prompt": _as_int(u.get("prompt_tokens")),
        "completion": _as_int(u.get("completion_tokens")),
        "total": _as_int(u.get("total_tokens")),
        "cached": _as_int(cached),
    }


def usage_from_ai_response(entry: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Extract normalized usage from a trace ai_responses[] entry."""
    if not isinstance(entry, Mapping):
        return None
    body = entry.get("body")
    if isinstance(body, Mapping) and isinstance(body.get("usage"), Mapping):
        return normalize_usage(body["usage"])
    if isinstance(entry.get("usage"), Mapping):
        return normalize_usage(entry["usage"])
    return None


def _has_billing(n: Mapping[str, int] | None) -> bool:
    if not n:
        return False
    return bool(n.get("prompt") or n.get("completion") or n.get("total"))


def _step_usage(step: Mapping[str, Any]) -> dict[str, int] | None:
    u = step.get("usage")
    if not isinstance(u, Mapping):
        return None
    n = normalize_usage(u)
    return n if _has_billing(n) else None


def sum_provider_tokens(
    *,
    steps: Sequence[Mapping[str, Any]] | None = None,
    ai_responses: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Sum provider billing tokens across LLM hops (Hub-identical).

    Prefers ``steps[].usage`` for ``type in {llm, force_final}``.
    When a billing step lacks usage, fills from ``ai_responses`` in order
    without double-counting hops that already had step usage.
    If there are no llm/force_final steps but ai_responses exist, sums all
    response usages (legacy traces).
    """
    llmish = [
        s
        for s in (steps or ())
        if isinstance(s, Mapping) and s.get("type") in _LLM_STEP_TYPES
    ]
    responses = [r for r in (ai_responses or ()) if isinstance(r, Mapping)]

    prompt = completion = total = cached = 0

    if not llmish:
        # No typed steps — fall back to every ai_response with usage.
        for entry in responses:
            n = usage_from_ai_response(entry)
            if not _has_billing(n):
                continue
            assert n is not None
            prompt += n["prompt"]
            completion += n["completion"]
            total += n["total"]
            cached += n["cached"]
    else:
        # Index-align llmish steps with ai_responses (one HTTP hop each).
        for i, s in enumerate(llmish):
            n = _step_usage(s)
            if n is None and i < len(responses):
                cand = usage_from_ai_response(responses[i])
                if _has_billing(cand):
                    n = cand
            if n is None:
                n = {"prompt": 0, "completion": 0, "total": 0, "cached": 0}
            prompt += n["prompt"]
            completion += n["completion"]
            total += n["total"]
            cached += n["cached"]

    if total == 0 and (prompt or completion):
        total = prompt + completion
    extra = max(0, total - prompt - completion)
    ok = bool(total or prompt or completion)
    return {
        "prompt": prompt,
        "completion": completion,
        "total": total,
        "cached": cached,
        "extra": extra,
        "ok": ok,
    }


def attach_trace_tokens(trace: MutableMapping[str, Any]) -> dict[str, Any]:
    """Mutate ``trace[\"tokens\"]`` with Hub-shaped provider rollup; return it."""
    steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
    ai_responses = (
        trace.get("ai_responses") if isinstance(trace.get("ai_responses"), list) else []
    )
    tokens = sum_provider_tokens(steps=steps, ai_responses=ai_responses)
    trace["tokens"] = tokens
    return tokens
