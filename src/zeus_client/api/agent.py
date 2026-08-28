"""Public agent-plane facade on ZeusRuntime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from zeus_client.application.agent_turn import AgentTurnUseCase, run_agent_turn
from zeus_client.application.middleware import MiddlewareChain, SecurityHooks
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
        self._middleware = MiddlewareChain(items=[SecurityHooks()])

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
        enable_sessions: bool | None = None,
        base_id: str | None = None,
        llm: Any = None,
        zeus: Any = None,
        rewind: bool | None = None,
    ) -> TurnResult:
        llm = self._rt.services.llm if llm is None else llm
        if llm is None:
            raise ZeusClientError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="api.agent",
                public_message="LLM port not wired on runtime",
            )
        zeus = self._rt.services.zeus if zeus is None else zeus
        cs = settings or self._rt.config.settings
        pack_schema = None
        cr = chat_request
        extra_notes: list[str] = []
        tgt = target or self._rt.config.target
        if cr is None:
            try:
                loaded = await self._rt.catalog.load_for_turn(cs.mode, target=tgt, base_id=base_id)
                cr = loaded.body
                pack_schema = loaded.response_output_schema
                extra_notes.append(f"chat_request: {loaded.source}")
            except ZeusClientError:
                cr = None
        else:
            merged = await self._rt.catalog.ensure_scope_brief(cr, target=tgt, mode=cs.mode)
            cr = merged.body
            extra_notes.append(merged.note)
            if merged.req_id:
                extra_notes.append(f"scope_brief.req_id={merged.req_id}")
        sessions_on = bool(cs.durable_sessions) if enable_sessions is None else enable_sessions
        req = TurnRequest(
            message=message,
            target=tgt,
            settings=cs,
            session=session,
            prior_messages=prior_messages,
            system_prompt=system_prompt or "You are a helpful Zeus data assistant.",
            tools=tools,
            chat_request=cr,
            base_id=base_id,
            pack_schema=pack_schema,
            chat_id=chat_id,
            model=model or self._rt.config.llm.model,
            enable_sessions=sessions_on,
        )
        result = await run_agent_turn(
            req,
            llm=llm,
            zeus=zeus,
            journal=self._rt.journal,
            middleware=self._middleware,
            default_settings=self._rt.config.settings,
            debug_policy=(
                replace(self._rt.config.debug, rewind=bool(rewind))
                if rewind is not None
                else self._rt.config.debug
            ),
            hub_base_url=self._rt.config.debug.hub_base_url,
            session_lifecycle=getattr(self._rt.services, "session_lifecycle", None),
            zeus_url=self._rt.config.zeus.url,
            client_floor=self._rt.config.client_floor,
            extra_notes=tuple(extra_notes),
            ids=self._rt.services.ids,
            client_ip=self._rt.config.client.ip_address,
            agent_memory=self._rt.services.agent_memory,
            semantic_cache=self._rt.config.semantic_cache,
            auth_mode=self._rt.config.zeus.auth_mode,
            metrics=self._rt.services.metrics,
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
            agent_memory=self._rt.services.agent_memory,
            semantic_cache=self._rt.config.semantic_cache,
            auth_mode=self._rt.config.zeus.auth_mode,
            metrics=self._rt.services.metrics,
        )
