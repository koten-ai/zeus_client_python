"""Isolated Mode 2 unit — no catalog, no LLM."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

from zeus_client.application.units_transport import verb_overrides
from zeus_client.domain.errors import ErrorCode, JobError, ZeusToolError
from zeus_client.domain.jobs import UnitConfig, UnitKind, UnitResult, UnitStatus, validate_unit_map
from zeus_client.domain.journal.events import EVENT_UNIT_FINISHED, EVENT_UNIT_STARTED, JournalEvent

__all__ = ["run_direct_unit"]


def _append_unit_event(
    rt: Any, typ: str, *, job_id: str | None, unit_id: str, data: Mapping[str, Any]
) -> None:
    rt.journal.append(
        JournalEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            ts_ms=int(rt.services.clock.now_ms()),
            type=typ,
            component="application.units_direct",
            turn_id=unit_id,
            span_id=None,
            parent_span_id=None,
            data=dict(data) | {"job_id": job_id, "unit_id": unit_id},
        )
    )


async def run_direct_unit(
    rt: Any,
    unit: UnitConfig,
    *,
    job_id: str | None = None,
    wave: int | None = None,
    plan_epoch: int = 0,
    cancel_event: asyncio.Event | None = None,
) -> UnitResult:
    validate_unit_map([unit])
    if unit.kind is not UnitKind.ZEUS_DIRECT:
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="application.units_direct")
    if cancel_event is not None and cancel_event.is_set():
        return UnitResult(unit_id=unit.unit_id, status=UnitStatus.CANCELLED, plan_epoch=plan_epoch)
    call = dict(unit.call or {})
    verb = str(call.get("verb") or "").strip()
    if not verb:
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="application.units_direct")
    body = call.get("body")
    if body is not None and not isinstance(body, Mapping):
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="application.units_direct")

    payload = {"wave": wave, "plan_epoch": plan_epoch, "verb": verb}
    _append_unit_event(rt, EVENT_UNIT_STARTED, job_id=job_id, unit_id=unit.unit_id, data=payload)
    try:
        result = await rt.data.verb(
            verb,
            body if isinstance(body, Mapping) else {},
            target=unit.target(),
            chat_id=job_id or unit.unit_id,
            turn_id=unit.unit_id,
            **verb_overrides(unit),
        )
    except ZeusToolError as exc:
        _append_unit_event(
            rt,
            EVENT_UNIT_FINISHED,
            job_id=job_id,
            unit_id=unit.unit_id,
            data=payload | {"status": "error"},
        )
        return UnitResult(
            unit_id=unit.unit_id,
            status=UnitStatus.ERROR,
            error_code=exc.code.value,
            plan_epoch=plan_epoch,
        )
    except Exception as exc:
        _append_unit_event(
            rt,
            EVENT_UNIT_FINISHED,
            job_id=job_id,
            unit_id=unit.unit_id,
            data=payload | {"status": "error"},
        )
        code = getattr(getattr(exc, "code", None), "value", None) or ErrorCode.ZEUS_TRANSPORT.value
        return UnitResult(
            unit_id=unit.unit_id,
            status=UnitStatus.ERROR,
            error_code=str(code),
            plan_epoch=plan_epoch,
        )

    req_ids = (
        tuple(result.req_ids) if result.req_ids else ((result.req_id,) if result.req_id else ())
    )
    status = UnitStatus.OK if result.ok else UnitStatus.ERROR
    _append_unit_event(
        rt,
        EVENT_UNIT_FINISHED,
        job_id=job_id,
        unit_id=unit.unit_id,
        data=payload | {"status": status.value, "req_id": req_ids[-1] if req_ids else None},
    )
    return UnitResult(
        unit_id=unit.unit_id,
        status=status,
        answer="",
        req_ids=req_ids,
        artifacts={"body": dict(result.body)},
        error_code=None if result.ok else (result.error or ErrorCode.ZEUS_HTTP_4XX.value),
        plan_epoch=plan_epoch,
    )
