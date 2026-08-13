"""Hub debug HTTP port (optional hydrate)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["HubDebugPort"]


@runtime_checkable
class HubDebugPort(Protocol):
    async def get_req(self, req_id: str) -> dict[str, Any]: ...

    async def get_session(self, session_id: str) -> dict[str, Any]: ...
