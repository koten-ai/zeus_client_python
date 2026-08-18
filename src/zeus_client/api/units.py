"""Public Mode 3 units facade — wraps Mode 1 / Mode 2 with isolation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from zeus_client.application.units_agent import run_agent_unit
from zeus_client.application.units_direct import run_direct_unit
from zeus_client.domain.jobs import UnitConfig, UnitKind, UnitResult
from zeus_client.domain.errors import ErrorCode, JobError

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["UnitsAPI"]


class UnitsAPI:
    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    async def agent_turn(
        self,
        unit: UnitConfig,
        *,
        job_id: str | None = None,
        wave: int | None = None,
        plan_epoch: int = 0,
        job_models: Mapping[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> UnitResult:
        if unit.kind is UnitKind.ZEUS_DIRECT:
            return await self.zeus_direct(
                unit, job_id=job_id, wave=wave, plan_epoch=plan_epoch, cancel_event=cancel_event
            )
        return await run_agent_unit(
            self._rt,
            unit,
            job_id=job_id,
            wave=wave,
            plan_epoch=plan_epoch,
            job_models=job_models,
            cancel_event=cancel_event,
        )

    async def zeus_direct(
        self,
        unit: UnitConfig,
        *,
        job_id: str | None = None,
        wave: int | None = None,
        plan_epoch: int = 0,
        cancel_event: asyncio.Event | None = None,
    ) -> UnitResult:
        if unit.kind is UnitKind.AGENT_TURN:
            raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="api.units")
        return await run_direct_unit(
            self._rt,
            unit,
            job_id=job_id,
            wave=wave,
            plan_epoch=plan_epoch,
            cancel_event=cancel_event,
        )
