"""Public session-plane facade — durable session flags + semantic cache."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from zeus_client.adapters.zeus_http.headers import TRACE_CLASS_AGENT, correlation_headers
from zeus_client.application.semantic_cache import (
    isolation_user_id,
    local_disabled_status,
    recall_and_inject,
    skipped_recall,
    skipped_write,
    write_memory_block,
)
from zeus_client.config.models import SemanticCacheConfig
from zeus_client.ports.agent_memory import AgentMemoryStatus, RecallResult, WriteResult

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["SessionAPI", "SemanticCacheAPI"]


class SemanticCacheAPI:
    """``rt.session.semantic_cache`` — L0 recall / write / status (ZF-WISH-001)."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    def _cfg(self) -> SemanticCacheConfig:
        return self._rt.config.semantic_cache

    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        h = correlation_headers(
            mode=self._rt.config.settings.mode,
            trace_class=TRACE_CLASS_AGENT,
        )
        if extra:
            h.update(dict(extra))
        return h

    async def status(self) -> AgentMemoryStatus:
        cfg = self._cfg()
        if not cfg.enabled:
            return local_disabled_status()
        port = self._rt.services.agent_memory
        if port is None:
            return local_disabled_status()
        result = await port.status()
        if isinstance(result, AgentMemoryStatus):
            return result
        return local_disabled_status()

    async def recall(
        self,
        query: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> RecallResult:
        cfg = self._cfg()
        if not cfg.enabled:
            return skipped_recall("disabled")
        port = self._rt.services.agent_memory
        messages: list[dict[str, Any]] = [{"role": "system", "content": ""}]
        result, _snippet = await recall_and_inject(
            port,
            cfg,
            messages,
            query,
            mode="agent",
            headers=self._headers(headers),
            user_id=isolation_user_id(cfg, self._rt.config.zeus.auth_mode),
            target=self._rt.config.target,
            metrics=self._rt.services.metrics,
        )
        return result

    async def write(
        self,
        text: str,
        *,
        type: str | None = None,
        summary: str | None = None,
        headers: Mapping[str, str] | None = None,
        zeus_session_id: str | None = None,
    ) -> WriteResult:
        cfg = self._cfg()
        if not cfg.enabled:
            return skipped_write("disabled")
        return await write_memory_block(
            self._rt.services.agent_memory,
            cfg,
            text,
            mode="agent",
            block_type=type,
            summary=summary,
            headers=self._headers(headers),
            user_id=isolation_user_id(cfg, self._rt.config.zeus.auth_mode),
            zeus_session_id=zeus_session_id,
            target=self._rt.config.target,
            metrics=self._rt.services.metrics,
            explicit=True,
        )


class SessionAPI:
    """``rt.session`` — session-scoped flags and actions."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime
        self.semantic_cache = SemanticCacheAPI(runtime)
