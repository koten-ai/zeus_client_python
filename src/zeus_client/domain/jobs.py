"""Mode 3 job / unit types + isolation validation (family jobs/units)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from zeus_client.config.models import DataTarget
from zeus_client.domain.errors import ErrorCode, JobError

__all__ = [
    "UnitKind",
    "UnitStatus",
    "JobBudgets",
    "UnitConfig",
    "UnitResult",
    "JobHandle",
    "JobEvent",
    "JobSnapshot",
    "validate_unit_map",
]


class UnitKind(str, Enum):
    AGENT_TURN = "agent_turn"
    ZEUS_DIRECT = "zeus_direct"
    HTTP_JSON = "http_json"  # not implemented this train


class UnitStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEAD_END = "dead_end"


@dataclass(frozen=True, slots=True)
class JobBudgets:
    max_workers: int = 4
    wall_ms: int = 120_000
    max_waves: int = 4
    max_replans: int = 2
    max_evidence_keys: int = 32
    disable_early_cancel: bool = False

    def validate(self) -> None:
        if self.max_workers < 1 or self.wall_ms < 1 or self.max_waves < 1:
            raise JobError(
                code=ErrorCode.JOBS_BUDGET_INVALID,
                component="domain.jobs",
                public_message="job budget invalid",
            )


@dataclass(frozen=True, slots=True)
class UnitConfig:
    unit_id: str
    kind: UnitKind
    goal: str
    zeus_url: str | None = None
    bucket: str | None = None
    scope: str | None = None
    collection: str | None = None
    auth_mode: str | None = None
    password_env: str | None = None  # name only
    token_env: str | None = None
    username: str | None = None
    catalog_mode: str | None = None
    base_id: str | None = None
    chat_request: Mapping[str, Any] | None = None
    llm: Mapping[str, Any] | None = None
    call: Mapping[str, Any] | None = None
    share_session_id: str | None = None
    max_rounds: int | None = None

    def target(self) -> DataTarget:
        return DataTarget(
            bucket=self.bucket or "",
            scope=self.scope or "",
            collection=self.collection or "",
        )

    def to_public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "goal": self.goal,
            "zeus_url": self.zeus_url,
            "bucket": self.bucket,
            "scope": self.scope,
            "collection": self.collection,
            "auth_mode": self.auth_mode,
            "catalog_mode": self.catalog_mode,
            "base_id": self.base_id,
            "llm": {
                k: v
                for k, v in dict(self.llm or {}).items()
                if k in {"model", "api_key_env", "temperature", "base_url", "provider"}
            },
            "has_chat_request": self.chat_request is not None,
            "share_session_id": bool(self.share_session_id),
        }
        if self.password_env:
            out["password_env"] = self.password_env
        if self.token_env:
            out["token_env"] = self.token_env
        return out


@dataclass(frozen=True, slots=True)
class UnitResult:
    unit_id: str
    status: UnitStatus
    answer: str = ""
    req_ids: tuple[str, ...] = ()
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    dead_end: bool = False
    plan_epoch: int = 0


@dataclass(frozen=True, slots=True)
class JobHandle:
    job_id: str
    status: str = "accepted"
    seq: int = 0


@dataclass(frozen=True, slots=True)
class JobEvent:
    seq: int
    type: str
    job_id: str
    ts_ms: int
    unit_id: str | None = None
    wave: int | None = None
    plan_epoch: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "job_id": self.job_id,
            "ts_ms": self.ts_ms,
            "unit_id": self.unit_id,
            "wave": self.wave,
            "plan_epoch": self.plan_epoch,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    status: str
    seq: int
    partial: bool = False
    unit_summaries: tuple[Mapping[str, Any], ...] = ()
    answer: str = ""


def validate_unit_map(units: Sequence[UnitConfig]) -> None:
    if len(units) < 1:
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="domain.jobs")
    seen: set[str] = set()
    sessions: dict[str, str] = {}
    for u in units:
        if not u.unit_id or u.unit_id in seen:
            raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="domain.jobs")
        seen.add(u.unit_id)
        if u.kind is UnitKind.HTTP_JSON:
            raise JobError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="domain.jobs",
                public_message="http_json units are not implemented in this SDK train",
            )
        if not u.zeus_url or not u.bucket or not u.scope or not u.collection:
            raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="domain.jobs")
        if u.kind is UnitKind.AGENT_TURN:
            if not (u.base_id or u.catalog_mode or u.chat_request):
                raise JobError(code=ErrorCode.UNITS_CATALOG_MISSING, component="domain.jobs")
        if u.share_session_id:
            prev = sessions.get(u.share_session_id)
            if prev and prev != u.unit_id:
                raise JobError(code=ErrorCode.UNITS_ISOLATION, component="domain.jobs")
            sessions[u.share_session_id] = u.unit_id
