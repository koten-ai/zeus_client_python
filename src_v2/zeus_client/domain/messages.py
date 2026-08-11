"""Turn message + result types for the agent plane (ZCM-004)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from zeus_client_v2.config.models import ClientSettings, DataTarget
from zeus_client_v2.domain.layer_a import LayerA
from zeus_client_v2.domain.policy import PolicyDecision
from zeus_client_v2.domain.session import SessionHandle

__all__ = [
    "TurnStatus",
    "Message",
    "ErrorInfo",
    "StructuredResult",
    "DebugBundle",
    "TurnRequest",
    "TurnResult",
]


class TurnStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    REFUSED = "refused"
    CLARIFY = "clarify"
    MAX_ROUNDS = "max_rounds"


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str | None = None
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [dict(t) for t in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False
    component: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StructuredResult:
    layer_a: Mapping[str, Any] | None = None
    policy: str | None = None
    flags: Mapping[str, bool] = field(default_factory=dict)
    ui: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    policy_reason: str = ""


@dataclass(frozen=True, slots=True)
class DebugBundle:
    """Turn debug plane — journal export + public_trace + notes (not user answer)."""

    turn_id: str = ""
    notes: tuple[str, ...] = ()
    rounds: int = 0
    ai_process_result: bool = True
    ai_process_result_exit: str | None = None
    public_trace: Mapping[str, Any] = field(default_factory=dict)
    hops: tuple[Mapping[str, Any], ...] = ()
    journal_event_count: int = 0
    hooks_jailbreak_score: float = 0.0


@dataclass(frozen=True, slots=True)
class TurnRequest:
    message: str
    target: DataTarget = field(default_factory=DataTarget)
    settings: ClientSettings | None = None
    session: SessionHandle | None = None
    prior_messages: tuple[Mapping[str, Any], ...] = ()
    # Catalog / prompt materials (caller or runtime injects; agent turn does not invent stamps)
    system_prompt: str = "You are a helpful Zeus data assistant."
    tools: tuple[Mapping[str, Any], ...] = ()
    chat_request: Mapping[str, Any] | None = None
    base_id: str | None = None
    chat_id: str | None = None
    model: str | None = None
    # When False, skip durable session setup/commit (unit tests / pure offline)
    enable_sessions: bool = False


@dataclass(frozen=True, slots=True)
class TurnResult:
    answer: str
    status: TurnStatus
    structured: StructuredResult | None
    session: SessionHandle | None
    debug: DebugBundle
    error: ErrorInfo | None
    messages: tuple[Mapping[str, Any], ...]
    layer_a: LayerA | None = None
    policy: PolicyDecision | None = None
