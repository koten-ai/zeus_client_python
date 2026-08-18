"""Sequential test-only job runtime. Not a product orchestrator."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

from zeus_client.api.units import UnitsAPI
from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import (
    JobBudgets,
    JobEvent,
    JobHandle,
    JobSnapshot,
    UnitConfig,
    UnitKind,
    UnitStatus,
)
from zeus_client.domain.journal.events import EVENT_JOB_FINISHED, EVENT_JOB_STARTED

__all__ = ["FakeJobRuntime"]


class FakeJobRuntime:
    """Executes units in input order via UnitsAPI. No planner LLM. Tests only."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime
        self._snaps: dict[str, JobSnapshot] = {}
        self._events: dict[str, list[JobEvent]] = {}
        self._cancels: dict[str, asyncio.Event] = {}

    def _now(self) -> int:
        return int(self._rt.services.clock.now_ms())

    def _emit(self, job_id: str, typ: str, *, unit_id: str | None = None, payload: Mapping[str, Any] | None = None) -> JobEvent:
        seq = len(self._events.setdefault(job_id, [])) + 1
        ev = JobEvent(
            seq=seq,
            type=typ,
            job_id=job_id,
            ts_ms=self._now(),
            unit_id=unit_id,
            payload=dict(payload or {}),
        )
        self._events[job_id].append(ev)
        return ev

    async def run(self, request: Mapping[str, Any]) -> JobHandle:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        units: list[UnitConfig] = list(request.get("units") or [])
        budgets: JobBudgets = request.get("budgets") or JobBudgets()
        self._cancels[job_id] = asyncio.Event()
        self._events[job_id] = []
        self._snaps[job_id] = JobSnapshot(job_id=job_id, status="running", seq=0)
        self._emit(job_id, EVENT_JOB_STARTED, payload={"goal": request.get("goal")})

        units_api = UnitsAPI(self._rt)
        summaries: list[Mapping[str, Any]] = []
        any_ok = False
        any_err = False
        for unit in units:
            if self._cancels[job_id].is_set():
                break
            if unit.kind is UnitKind.AGENT_TURN:
                result = await units_api.agent_turn(
                    unit, job_id=job_id, cancel_event=self._cancels[job_id]
                )
            else:
                result = await units_api.zeus_direct(
                    unit, job_id=job_id, cancel_event=self._cancels[job_id]
                )
            if result.status is UnitStatus.OK:
                any_ok = True
            else:
                any_err = True
            summaries.append(
                {
                    "unit_id": result.unit_id,
                    "status": result.status.value,
                    "error_code": result.error_code,
                }
            )

        cancelled = self._cancels[job_id].is_set()
        if cancelled:
            status = "cancelled"
        elif any_err and any_ok:
            status = "partial"
        elif any_err:
            status = "error"
        else:
            status = "ok"
        self._emit(job_id, EVENT_JOB_FINISHED, payload={"status": status})
        events = self._events[job_id]
        self._snaps[job_id] = JobSnapshot(
            job_id=job_id,
            status=status,
            seq=events[-1].seq if events else 0,
            partial=status == "partial",
            unit_summaries=tuple(summaries),
        )
        return JobHandle(job_id=job_id, status="running", seq=1)

    def watch(self, job_id: str, *, after_seq: int = 0) -> AsyncIterator[JobEvent]:
        async def _gen() -> AsyncIterator[JobEvent]:
            events = self._events.get(job_id)
            if events is None:
                raise JobError(code=ErrorCode.JOBS_NOT_FOUND, component="adapters.jobs_fake")
            for ev in events:
                if ev.seq > after_seq:
                    yield ev

        return _gen()

    async def get(self, job_id: str) -> JobSnapshot:
        snap = self._snaps.get(job_id)
        if snap is None:
            raise JobError(code=ErrorCode.JOBS_NOT_FOUND, component="adapters.jobs_fake")
        return snap

    async def cancel(self, job_id: str) -> JobSnapshot:
        ev = self._cancels.get(job_id)
        if ev is None:
            raise JobError(code=ErrorCode.JOBS_NOT_FOUND, component="adapters.jobs_fake")
        ev.set()
        prev = self._snaps.get(job_id)
        snap = JobSnapshot(
            job_id=job_id,
            status="cancelled",
            seq=(prev.seq if prev else 0),
            partial=bool(prev.partial) if prev else False,
            unit_summaries=prev.unit_summaries if prev else (),
        )
        self._snaps[job_id] = snap
        return snap
