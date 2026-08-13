"""Middleware hooks for agent turn (replaces V1 AgentHooks surface).

Errors are isolated unless ``critical=True`` — never crash a successful turn
for non-critical middleware failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

__all__ = [
    "MiddlewareContext",
    "Middleware",
    "MiddlewareChain",
    "NoopMiddleware",
]


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
