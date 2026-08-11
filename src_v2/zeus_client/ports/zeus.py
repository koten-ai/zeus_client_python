"""Zeus HTTP port (verb/auth/session) — full methods filled as adapters land."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from zeus_client_v2.ports import AuthContext, VerbHopResult, VerbRequest
from zeus_client_v2.config.models import DataTarget

__all__ = ["ZeusPort"]


@runtime_checkable
class ZeusPort(Protocol):
    async def resolve_auth(self, target: DataTarget, *, force: bool = False) -> AuthContext: ...

    async def call_verb(self, req: VerbRequest) -> VerbHopResult: ...
