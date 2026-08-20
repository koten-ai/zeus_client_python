"""Agent memory port — Zeus ``/v2/agent_memory/*`` (ZF-WISH-001).

Not a V2 data-plane verb. Not the graph tool ``agent_memory.read``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AgentMemoryStatus",
    "RecalledBlock",
    "RecallResult",
    "WriteResult",
    "AgentMemoryPort",
]


@dataclass(frozen=True, slots=True)
class AgentMemoryStatus:
    enabled: bool
    store: bool = False
    embedder: bool = False
    recall_mode: str = ""
    feature: str = "semantic_agent_cache"
    status_code: int = 200
    req_id: str | None = None
    error: str | None = None
    url: str = ""

    @property
    def available(self) -> bool:
        return bool(self.enabled)


@dataclass(frozen=True, slots=True)
class RecalledBlock:
    block_id: str = ""
    type: str = "conversational"
    text: str = ""
    summary: str = ""
    score: float = 0.0
    created_at: str = ""

    def to_mapping(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "type": self.type,
            "text": self.text,
            "summary": self.summary,
            "score": self.score,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class RecallResult:
    ok: bool
    status_code: int
    req_id: str | None = None
    blocks: tuple[RecalledBlock, ...] = ()
    embed_model: str | None = None
    mode: str = ""
    latency_ms: int = 0
    error: str | None = None
    url: str = ""
    skipped: bool = False
    skip_reason: str = ""

    def block_maps(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(b.to_mapping() for b in self.blocks)


@dataclass(frozen=True, slots=True)
class WriteResult:
    ok: bool
    status_code: int
    req_id: str | None = None
    block_id: str | None = None
    type: str = ""
    ttl_seconds: int = 0
    error: str | None = None
    url: str = ""
    skipped: bool = False
    skip_reason: str = ""


@runtime_checkable
class AgentMemoryPort(Protocol):
    async def status(self) -> AgentMemoryStatus: ...

    async def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        types: Sequence[str] = (),
        min_score: float = 0.0,
        timeout_ms: int | None = None,
        headers: Mapping[str, str] | None = None,
        user_id: str | None = None,
        memory_session_id: str | None = None,
        bucket: str | None = None,
        scope: str | None = None,
    ) -> RecallResult: ...

    async def write_block(
        self,
        text: str,
        *,
        type: str = "conversational",
        summary: str | None = None,
        ttl_seconds: int | None = None,
        headers: Mapping[str, str] | None = None,
        user_id: str | None = None,
        zeus_session_id: str | None = None,
        memory_session_id: str | None = None,
        bucket: str | None = None,
        scope: str | None = None,
    ) -> WriteResult: ...
