"""LLM completion port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from zeus_client_v2.ports import LlmRequest, LlmResponse

__all__ = ["LlmPort"]


@runtime_checkable
class LlmPort(Protocol):
    async def complete(self, req: LlmRequest) -> LlmResponse: ...
