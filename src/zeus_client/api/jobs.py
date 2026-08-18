"""Public Mode 3 jobs facade — fail closed without a host."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import (
    JobBudgets,
    JobEvent,
    JobHandle,
    JobSnapshot,
    UnitConfig,
    UnitKind,
    validate_unit_map,
)
from zeus_client.domain.journal.events import EVENT_JOB_STARTED, JournalEvent
from zeus_client.ports.jobs import JobRuntimePort

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["JobsAPI"]


def _unavailable() -> JobError:
    return JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="api.jobs")


def _parse_units(raw: Sequence[Mapping[str, Any]] | Sequence[UnitConfig]) -> list[UnitConfig]:
    out: list[UnitConfig] = []
    for item in raw:
        if isinstance(item, UnitConfig):
            out.append(item)
            continue
        kind = item.get("kind") or UnitKind.ZEUS_DIRECT.value
        out.append(
            UnitConfig(
                unit_id=str(item.get("unit_id") or ""),
                kind=UnitKind(str(kind)),
                goal=str(item.get("goal") or ""),
                zeus_url=item.get("zeus_url"),
                bucket=item.get("bucket"),
                scope=item.get("scope"),
                collection=item.get("collection"),
                auth_mode=item.get("auth_mode"),
                password_env=item.get("password_env"),
                token_env=item.get("token_env"),
                catalog_mode=item.get("catalog_mode"),
                base_id=item.get("base_id"),
                chat_request=item.get("chat_request"),
                llm=item.get("llm"),
                call=item.get("call"),
                share_session_id=item.get("share_session_id"),
                max_rounds=item.get("max_rounds"),
            )
        )
    return out


class JobsAPI:
    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    def _port(self) -> JobRuntimePort:
        port = getattr(self._rt.services, "jobs", None)
        if port is None:
            raise _unavailable()
        return port

    async def run(
        self,
        goal: str,
        *,
        pack: str | None = None,
        budgets: JobBudgets | None = None,
        units: Sequence[UnitConfig | Mapping[str, Any]] | None = None,
        scope_map: Sequence[UnitConfig | Mapping[str, Any]] | None = None,
        models: Mapping[str, Any] | None = None,
    ) -> JobHandle:
        parsed = _parse_units(list(units or scope_map or ()))
        bag = budgets or JobBudgets()
        bag.validate()
        validate_unit_map(parsed)
        port = self._port()
        handle = await port.run(
            {
                "goal": goal,
                "pack": pack,
                "budgets": bag,
                "units": parsed,
                "models": dict(models or {}),
            }
        )
        self._rt.journal.append(
            JournalEvent(
                event_id=f"job_{handle.job_id}_start",
                ts_ms=int(self._rt.services.clock.now_ms()),
                type=EVENT_JOB_STARTED,
                component="api.jobs",
                turn_id=handle.job_id,
                span_id=None,
                parent_span_id=None,
                data={"job_id": handle.job_id, "goal": goal, "unit_count": len(parsed)},
            )
        )
        return handle

    def watch(self, job_id: str, *, after_seq: int = 0) -> AsyncIterator[JobEvent]:
        return self._port().watch(job_id, after_seq=after_seq)

    async def get(self, job_id: str) -> JobSnapshot:
        return await self._port().get(job_id)

    async def cancel(self, job_id: str) -> JobSnapshot:
        return await self._port().cancel(job_id)
