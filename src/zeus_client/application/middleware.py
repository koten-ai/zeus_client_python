"""Middleware hooks for agent turn (replaces V1 AgentHooks surface).

Errors are isolated unless ``critical=True`` — never crash a successful turn
for non-critical middleware failures.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from zeus_client.security.jailbreak import (
    DENIED_VERB_SCORE,
    HARD_REFUSE_SCORE,
    JailbreakAssessment,
    assess_payload,
    assess_turn,
)

__all__ = [
    "MiddlewareContext",
    "Middleware",
    "MiddlewareChain",
    "NoopMiddleware",
    "SecurityHooks",
    "inspect_jailbreak",
]

_CLIENT_TERMINATE = frozenset({"return", "return_result"})


@dataclass
class MiddlewareContext:
    """Mutable per-turn bag visible to middleware."""

    turn_id: str = ""
    user_msg: str = ""
    round: int = 0
    notes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Middleware(Protocol):
    name: str
    critical: bool

    async def on_turn_start(self, ctx: MiddlewareContext) -> None: ...

    async def before_llm(self, ctx: MiddlewareContext, messages: list[dict[str, Any]]) -> None: ...

    async def after_llm(self, ctx: MiddlewareContext, response: Mapping[str, Any]) -> None: ...

    async def before_zeus(
        self, ctx: MiddlewareContext, name: str, args: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def after_zeus(
        self,
        ctx: MiddlewareContext,
        name: str,
        status: int,
        body: Mapping[str, Any] | str | None,
    ) -> None: ...

    async def on_turn_end(self, ctx: MiddlewareContext, answer: str) -> None: ...


@dataclass
class NoopMiddleware:
    name: str = "noop"
    critical: bool = False

    async def on_turn_start(self, ctx: MiddlewareContext) -> None:
        return None

    async def before_llm(self, ctx: MiddlewareContext, messages: list[dict[str, Any]]) -> None:
        return None

    async def after_llm(self, ctx: MiddlewareContext, response: Mapping[str, Any]) -> None:
        return None

    async def before_zeus(
        self, ctx: MiddlewareContext, name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        return args

    async def after_zeus(
        self,
        ctx: MiddlewareContext,
        name: str,
        status: int,
        body: Mapping[str, Any] | str | None,
    ) -> None:
        return None

    async def on_turn_end(self, ctx: MiddlewareContext, answer: str) -> None:
        return None


@dataclass
class MiddlewareChain:
    """Ordered middleware list with isolated error handling."""

    items: list[Any] = field(default_factory=list)

    def add(self, mw: Any) -> None:
        self.items.append(mw)

    async def _run(self, method: str, *args: Any, **kwargs: Any) -> Any:
        last = kwargs.pop("_default", None)
        result = last
        for mw in self.items:
            critical = bool(getattr(mw, "critical", False))
            name = getattr(mw, "name", type(mw).__name__)
            fn = getattr(mw, method, None)
            if fn is None:
                continue
            try:
                out = await fn(*args, **kwargs)
                if out is not None and method == "before_zeus":
                    result = out
            except Exception as exc:  # noqa: BLE001 — isolate non-critical
                ctx = args[0] if args else None
                note = f"middleware.{name}.{method}_failed: {exc}"
                if isinstance(ctx, MiddlewareContext):
                    ctx.notes.append(note)
                if critical:
                    raise
        return result

    async def on_turn_start(self, ctx: MiddlewareContext) -> None:
        await self._run("on_turn_start", ctx)

    async def before_llm(self, ctx: MiddlewareContext, messages: list[dict[str, Any]]) -> None:
        await self._run("before_llm", ctx, messages)

    async def after_llm(self, ctx: MiddlewareContext, response: Mapping[str, Any]) -> None:
        await self._run("after_llm", ctx, response)

    async def before_zeus(
        self, ctx: MiddlewareContext, name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        out = await self._run("before_zeus", ctx, name, args, _default=args)
        return out if isinstance(out, dict) else args

    async def after_zeus(
        self,
        ctx: MiddlewareContext,
        name: str,
        status: int,
        body: Mapping[str, Any] | str | None,
    ) -> None:
        await self._run("after_zeus", ctx, name, status, body)

    async def on_turn_end(self, ctx: MiddlewareContext, answer: str) -> None:
        await self._run("on_turn_end", ctx, answer)


def _fold_assessment(ctx: MiddlewareContext, assessment: JailbreakAssessment) -> None:
    prev = float(ctx.data.get("hooks_jailbreak_score") or 0.0)
    score = max(prev, float(assessment.score))
    ctx.data["hooks_jailbreak_score"] = min(1.0, score)
    if assessment.must_refuse or score >= HARD_REFUSE_SCORE:
        ctx.data["hooks_must_refuse"] = True
    hits = list(ctx.data.get("jailbreak_hits") or [])
    for hit in assessment.hits:
        if hit.attempt_id not in hits:
            hits.append(hit.attempt_id)
    ctx.data["jailbreak_hits"] = hits


def inspect_jailbreak(
    ctx: MiddlewareContext,
    payload: Any,
    *,
    surface: str,
) -> JailbreakAssessment:
    """Score a payload and fold the result into ``ctx.data`` (ZCP-101)."""
    assessment = assess_payload(payload, surface=surface)
    _fold_assessment(ctx, assessment)
    return assessment


def _deny_verb(ctx: MiddlewareContext, name: str) -> None:
    denied = list(ctx.data.get("denied_verbs") or [])
    if name not in denied:
        denied.append(name)
    ctx.data["denied_verbs"] = denied
    ctx.data["hooks_jailbreak_score"] = max(
        float(ctx.data.get("hooks_jailbreak_score") or 0.0), DENIED_VERB_SCORE
    )


@dataclass
class SecurityHooks:
    """Baseline AgentHooks: prompt-dump / secrets / denied verbs (CHECKLIST C / ZCP-101)."""

    name: str = "security"
    critical: bool = False
    denied_verbs: tuple[str, ...] = ()

    def score_jailbreak(self, ctx: MiddlewareContext) -> float:
        prior = ctx.data.get("prior_user_texts") or ()
        assessment = assess_turn(str(ctx.user_msg or ""), prior_user_texts=list(prior))
        _fold_assessment(ctx, assessment)
        if ctx.data.get("denied_verbs"):
            ctx.data["hooks_jailbreak_score"] = max(
                float(ctx.data.get("hooks_jailbreak_score") or 0.0), DENIED_VERB_SCORE
            )
        return min(1.0, float(ctx.data.get("hooks_jailbreak_score") or 0.0))

    def must_refuse(self, ctx: MiddlewareContext) -> bool:
        return self.score_jailbreak(ctx) >= HARD_REFUSE_SCORE

    async def on_turn_start(self, ctx: MiddlewareContext) -> None:
        score = self.score_jailbreak(ctx)
        ctx.data["hooks_jailbreak_score"] = score
        ctx.data["hooks_must_refuse"] = bool(ctx.data.get("hooks_must_refuse")) or (
            score >= HARD_REFUSE_SCORE
        )

    async def before_llm(self, ctx: MiddlewareContext, messages: list[dict[str, Any]]) -> None:
        return None

    async def after_llm(self, ctx: MiddlewareContext, response: Mapping[str, Any]) -> None:
        inspect_jailbreak(ctx, response.get("content"), surface="llm")
        for tc in response.get("tool_calls") or ():
            if not isinstance(tc, Mapping):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), Mapping) else {}
            inspect_jailbreak(ctx, (fn or {}).get("arguments"), surface="tool_args")

    async def before_zeus(
        self, ctx: MiddlewareContext, name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        allowed = ctx.data.get("catalog_tool_names") or set()
        unknown = bool(allowed) and name not in allowed and name not in _CLIENT_TERMINATE
        if name in self.denied_verbs or unknown:
            _deny_verb(ctx, name)
        inspect_jailbreak(ctx, args, surface="tool_args")
        return args

    async def after_zeus(
        self,
        ctx: MiddlewareContext,
        name: str,
        status: int,
        body: Mapping[str, Any] | str | None,
    ) -> None:
        assessment = inspect_jailbreak(ctx, body, surface="tool_body")
        if assessment.must_refuse:
            ctx.data["tool_body_override"] = json.dumps({"error": "untrusted_tool_payload"})

    async def on_turn_end(self, ctx: MiddlewareContext, answer: str) -> None:
        inspect_jailbreak(ctx, answer, surface="answer")
