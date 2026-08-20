"""Public agent-plane facade on ZeusRuntime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from zeus_client.application.agent_turn import AgentTurnUseCase, run_agent_turn
from zeus_client.application.middleware import MiddlewareChain
from zeus_client.config.models import ClientSettings, DataTarget
from zeus_client.domain.errors import ErrorCode, ZeusClientError
from zeus_client.domain.messages import TurnRequest, TurnResult

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["AgentAPI"]


class AgentAPI:
    """``rt.agent.run_turn(...)`` — typed agent plane."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime
        self._middleware = MiddlewareChain()

    @property
    def middleware(self) -> MiddlewareChain:
        return self._middleware

    async def run_turn(
        self,
        message: str,
        *,
        target: DataTarget | None = None,
        settings: ClientSettings | None = None,
        session: Any = None,
        prior_messages: tuple[Mapping[str, Any], ...] = (),
        system_prompt: str | None = None,
        tools: tuple[Mapping[str, Any], ...] = (),
        chat_request: Mapping[str, Any] | None = None,
        chat_id: str | None = None,
        model: str | None = None,
        enable_sessions: bool = False,
        llm: Any = None,
        zeus: Any = None,
    ) -> TurnResult:
        llm = self._rt.services.llm if llm is None else llm
        if llm is None:
            raise ZeusClientError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="api.agent",
                public_message="LLM port not wired on runtime",
            )
        zeus = self._rt.services.zeus if zeus is None else zeus
        req = TurnRequest(
            message=message,
            target=target or self._rt.config.target,
            settings=settings or self._rt.config.settings,
            session=session,
            prior_messages=prior_messages,
            system_prompt=system_prompt or "You are a helpful Zeus data assistant.",
            tools=tools,
            chat_request=chat_request,
            chat_id=chat_id,
            model=model or self._rt.config.llm.model,
            enable_sessions=enable_sessions,
        )
        result = await run_agent_turn(
            req,
            llm=llm,
            zeus=zeus,
            journal=self._rt.journal,
            middleware=self._middleware,
            default_settings=self._rt.config.settings,
            debug_policy=self._rt.config.debug,
            hub_base_url=self._rt.config.debug.hub_base_url,
            session_lifecycle=getattr(self._rt.services, "session_lifecycle", None),
            zeus_url=self._rt.config.zeus.url,
        )
        metrics = self._rt.services.metrics
        metrics.incr(
            "zeus_client_turns_total",
            labels={
                "status": result.status.value
                if hasattr(result.status, "value")
                else str(result.status),
                "mode": (settings or self._rt.config.settings).mode,
            },
        )
        if result.error is not None:
            metrics.incr(
                "zeus_client_errors_total",
                labels={"code": result.error.code or "agent_error"},
            )
        return result

    def use_case(self) -> AgentTurnUseCase:
        return AgentTurnUseCase(
            llm=self._rt.services.llm,
            zeus=self._rt.services.zeus,
            journal=self._rt.journal,
            middleware=self._middleware,
            default_settings=self._rt.config.settings,
        )
