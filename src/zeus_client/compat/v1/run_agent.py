"""Deprecated V1-shaped agent entry → ``rt.agent.run_turn``."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Mapping

from zeus_client.config.models import ClientSettings, DataTarget
from zeus_client.domain.messages import TurnResult

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["run_agent", "turn_result_as_v1_tuple"]

_DEPRECATION = (
    "zeus_client.compat.v1.run_agent is deprecated; "
    "use ZeusRuntime.agent.run_turn(...) instead"
)


def turn_result_as_v1_tuple(
    result: TurnResult,
) -> tuple[str, dict[str, Any], int, dict[str, Any]]:
    """Map :class:`TurnResult` to a V1-ish ``(answer, trace, rounds, session_meta)`` tuple."""
    trace = dict(result.debug.public_trace) if result.debug.public_trace else {}
    if result.debug.detective is not None:
        trace["detective"] = dict(result.debug.detective)
    if result.debug.preferred_req_id:
        trace.setdefault("session", {})
        if isinstance(trace.get("session"), dict):
            sess = dict(trace["session"])
            sess["preferred_req_id"] = result.debug.preferred_req_id
            trace["session"] = sess
    session_meta: dict[str, Any] = {}
    if result.session is not None:
        session_meta = {
            "session_id": getattr(result.session, "session_id", None)
            or getattr(result.session, "id", None),
            "round": getattr(result.session, "round", None),
        }
    return (
        result.answer,
        trace,
        int(result.debug.rounds or 0),
        session_meta,
    )


async def run_agent(
    message: str | None = None,
    *,
    runtime: ZeusRuntime,
    user_msg: str | None = None,
    target: DataTarget | None = None,
    settings: ClientSettings | Mapping[str, Any] | None = None,
    session: Any = None,
    prior_messages: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
    system_prompt: str | None = None,
    tools: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
    chat_request: Mapping[str, Any] | None = None,
    chat_id: str | None = None,
    model: str | None = None,
    enable_sessions: bool = False,
    legacy_tuple: bool = False,
    # Ignored V1 free-function leftovers (documented for greppers / migration):
    zeus_url: str | None = None,
    zcfg: Mapping[str, Any] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    api_version: str | None = None,
    mode: str | None = None,
    bucket: str | None = None,
    scope: str | None = None,
    collection: str | None = None,
    prior_turns: Any = None,
    **_ignored: Any,
) -> TurnResult | tuple[str, dict[str, Any], int, dict[str, Any]]:
    """Deprecated shim: call ``runtime.agent.run_turn``.

    Prefer the typed :class:`TurnResult`. Pass ``legacy_tuple=True`` for a
    deprecated ``(answer, trace, rounds, session_meta)`` return.
    """
    warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
    text = (message if message is not None else user_msg) or ""
    if not text.strip():
        raise ValueError("message/user_msg required")

    cs: ClientSettings | None
    if settings is None:
        cs = None
    elif isinstance(settings, ClientSettings):
        cs = settings
    else:
        # thin mapping → ClientSettings (known keys only)
        cs = ClientSettings(
            ai_process_result=bool(settings.get("ai_process_result", True)),
            max_rounds=int(settings.get("max_rounds", 8)),
            force_trace=bool(settings.get("force_trace", False)),
            mode=str(settings.get("mode", mode or "analytics")),
        )

    tgt = target
    if tgt is None and (bucket or scope or collection):
        tgt = DataTarget(
            bucket=bucket or runtime.config.target.bucket,
            scope=scope or runtime.config.target.scope,
            collection=collection or runtime.config.target.collection,
        )

    prior: tuple[Mapping[str, Any], ...]
    if prior_messages:
        prior = tuple(prior_messages)
    elif prior_turns:
        prior = tuple(prior_turns)  # type: ignore[arg-type]
    else:
        prior = ()

    result = await runtime.agent.run_turn(
        text,
        target=tgt,
        settings=cs,
        session=session,
        prior_messages=prior,
        system_prompt=system_prompt,
        tools=tuple(tools) if tools else (),
        chat_request=chat_request,
        chat_id=chat_id,
        model=model,
        enable_sessions=enable_sessions,
    )
    if legacy_tuple:
        return turn_result_as_v1_tuple(result)
    return result
