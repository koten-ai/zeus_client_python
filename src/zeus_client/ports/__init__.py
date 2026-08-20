"""Port protocols for V2 hexagonal adapters (no httpx in domain)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from zeus_client.config.models import DataTarget

__all__ = [
    "AuthContext",
    "VerbRequest",
    "VerbHopResult",
    "LlmRequest",
    "LlmResponse",
    "CatalogKey",
    "CatalogDocument",
    "ZeusPort",
    "LlmPort",
    "CatalogStorePort",
    "HubDebugPort",
    "SecretStorePort",
    "HttpPort",
    "Clock",
    "IdFactory",
    "AgentMemoryPort",
    "AgentMemoryStatus",
    "RecalledBlock",
    "RecallResult",
    "WriteResult",
]


@dataclass(frozen=True, slots=True)
class AuthContext:
    headers: Mapping[str, str] = field(default_factory=dict)
    mode: str = "none"


@dataclass(frozen=True, slots=True)
class VerbRequest:
    verb: str
    body: Mapping[str, Any]
    target: DataTarget
    mode_header: str = "analytics"
    headers: Mapping[str, str] = field(default_factory=dict)
    # Agent path may dispatch pipeline; Direct public surface must keep False.
    allow_pipeline: bool = False
    # Default omit X-Zeus-Req-Id (Zeus mints). Tests may pre-mint UUID v4.
    pre_mint_req_id: bool = False


@dataclass(frozen=True, slots=True)
class VerbHopResult:
    ok: bool
    status_code: int
    req_id: str | None
    body: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    url: str = ""


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[Mapping[str, Any], ...]
    model: str | None = None
    tools: tuple[Mapping[str, Any], ...] = ()
    temperature: float | None = None
    max_tokens: int | None = None
    conv_id: str | None = None  # cache routing key (xAI conv / OpenAI prompt_cache_key)


@dataclass(frozen=True, slots=True)
class LlmResponse:
    content: str | None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
    usage: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CatalogKey:
    mode: str
    bucket: str
    scope: str
    base_id: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogDocument:
    body: Mapping[str, Any]
    path: str | None = None
    contract_hash: str | None = None


# Re-export clock / id from dedicated modules for a single ports surface.
from zeus_client.ports.agent_memory import (  # noqa: E402
    AgentMemoryPort as AgentMemoryPort,
)
from zeus_client.ports.agent_memory import AgentMemoryStatus as AgentMemoryStatus
from zeus_client.ports.agent_memory import RecalledBlock as RecalledBlock
from zeus_client.ports.agent_memory import RecallResult as RecallResult
from zeus_client.ports.agent_memory import WriteResult as WriteResult
from zeus_client.ports.clock import Clock as Clock  # noqa: E402
from zeus_client.ports.id_factory import IdFactory as IdFactory  # noqa: E402


@runtime_checkable
class ZeusPort(Protocol):
    async def resolve_auth(self, target: DataTarget, *, force: bool = False) -> AuthContext: ...

    async def call_verb(self, req: VerbRequest) -> VerbHopResult: ...


@runtime_checkable
class LlmPort(Protocol):
    async def complete(self, req: LlmRequest) -> LlmResponse: ...


@runtime_checkable
class CatalogStorePort(Protocol):
    def load(self, key: CatalogKey) -> CatalogDocument: ...

    def save(self, key: CatalogKey, doc: CatalogDocument) -> None: ...


@runtime_checkable
class HubDebugPort(Protocol):
    async def get_req(self, req_id: str) -> dict[str, Any]: ...

    async def get_session(self, session_id: str) -> dict[str, Any]: ...


@runtime_checkable
class SecretStorePort(Protocol):
    def get(self, name: str) -> str | None: ...


@runtime_checkable
class HttpPort(Protocol):
    """Low-level HTTP (optional; Zeus/LLM adapters may own clients directly)."""

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        timeout_s: float | None = None,
    ) -> tuple[int, Mapping[str, str], bytes]: ...

    async def aclose(self) -> None: ...
