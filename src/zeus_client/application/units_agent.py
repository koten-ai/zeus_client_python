"""Isolated Mode 1 unit — worker LLM, no shared session by default."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

from zeus_client.application.units_transport import UnitScopedZeusPort
from zeus_client.config.models import ClientSettings
from zeus_client.domain.catalog import extract_scope_brief
from zeus_client.domain.errors import CatalogError, ErrorCode, JobError
from zeus_client.domain.jobs import UnitConfig, UnitKind, UnitResult, UnitStatus, validate_unit_map
from zeus_client.domain.journal.events import EVENT_UNIT_FINISHED, EVENT_UNIT_STARTED, JournalEvent
from zeus_client.domain.llm_roles import LlmRole, resolve_llm_slice
from zeus_client.domain.session import SessionHandle

__all__ = ["run_agent_unit"]


def _has_required_inject(chat_request: Mapping[str, Any] | None) -> bool:
    if not chat_request:
        return False
    if extract_scope_brief(chat_request):
        return True
    text = ""
    msgs = chat_request.get("messages") or []
    if msgs and isinstance(msgs[0], Mapping):
        text += str(msgs[0].get("content") or "")
    instr = chat_request.get("instructions") or {}
    if isinstance(instr, Mapping):
        text += str(instr.get("system_prompt") or "")
    return "## MINI-SCHEMA" in text


def _append_unit_event(
    rt: Any, typ: str, *, job_id: str | None, unit_id: str, data: Mapping[str, Any]
) -> None:
    rt.journal.append(
        JournalEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            ts_ms=int(rt.services.clock.now_ms()),
            type=typ,
            component="application.units_agent",
            turn_id=unit_id,
            span_id=None,
            parent_span_id=None,
            data=dict(data) | {"job_id": job_id, "unit_id": unit_id},
        )
    )


async def run_agent_unit(
    rt: Any,
    unit: UnitConfig,
    *,
    job_id: str | None = None,
    wave: int | None = None,
    plan_epoch: int = 0,
    job_models: Mapping[str, Any] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> UnitResult:
    validate_unit_map([unit])
    if unit.kind is not UnitKind.AGENT_TURN:
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="application.units_agent")
    if cancel_event is not None and cancel_event.is_set():
        return UnitResult(unit_id=unit.unit_id, status=UnitStatus.CANCELLED, plan_epoch=plan_epoch)

    chat_request: Mapping[str, Any] | None = dict(unit.chat_request) if unit.chat_request else None
    if chat_request is None:
        try:
            loaded = await rt.catalog.load(
                mode=unit.catalog_mode or rt.config.settings.mode,
                target=unit.target(),
            )
            chat_request = dict(loaded.body)
        except CatalogError as exc:
            raise JobError(
                code=ErrorCode.UNITS_CATALOG_MISSING,
                component="application.units_agent",
                public_message=exc.public_message,
            ) from exc
    if not _has_required_inject(chat_request):
        raise JobError(code=ErrorCode.UNITS_INJECT_MISSING, component="application.units_agent")

    slice_ = resolve_llm_slice(
        rt.config.llm,
        role=LlmRole.WORKER,
        jobs=rt.config.jobs,
        job_models=job_models,
        unit_llm=unit.llm,
        unit_id=unit.unit_id,
    )
    payload = {
        "wave": wave,
        "plan_epoch": plan_epoch,
        "llm.role": slice_.role,
        "llm.model": slice_.model,
        "api_key_env": slice_.api_key_env,
    }
    _append_unit_event(rt, EVENT_UNIT_STARTED, job_id=job_id, unit_id=unit.unit_id, data=payload)

    session = None
    if unit.share_session_id:
        session = SessionHandle(session_id=unit.share_session_id, round=0, enabled=True)

    settings = rt.config.settings
    if unit.max_rounds is not None:
        settings = ClientSettings(
            ai_process_result=settings.ai_process_result,
            max_rounds=unit.max_rounds,
            force_trace=settings.force_trace,
            mode=unit.catalog_mode or settings.mode,
            durable_sessions=False,
            sticky_flags=settings.sticky_flags,
            messages=settings.messages,
            soft_require_policy_action=settings.soft_require_policy_action,
            allow_array_triggers=settings.allow_array_triggers,
            app_output_on_error=settings.app_output_on_error,
            output_request=settings.output_request,
        )
    else:
        settings = ClientSettings(
            ai_process_result=settings.ai_process_result,
            max_rounds=settings.max_rounds,
            force_trace=settings.force_trace,
            mode=unit.catalog_mode or settings.mode,
            durable_sessions=False,
            sticky_flags=settings.sticky_flags,
            messages=settings.messages,
            soft_require_policy_action=settings.soft_require_policy_action,
            allow_array_triggers=settings.allow_array_triggers,
            app_output_on_error=settings.app_output_on_error,
            output_request=settings.output_request,
        )

    zeus = rt.services.zeus
    if zeus is not None:
        zeus = UnitScopedZeusPort(zeus, unit)
    llm = rt.llm_for_slice(slice_) if hasattr(rt, "llm_for_slice") else rt.services.llm

    try:
        result = await rt.agent.run_turn(
            unit.goal,
            target=unit.target(),
            settings=settings,
            session=session,
            chat_request=chat_request,
            chat_id=job_id or unit.unit_id,
            model=slice_.model,
            enable_sessions=False,
            zeus=zeus,
            llm=llm,
        )
    except Exception as exc:
        _append_unit_event(
            rt,
            EVENT_UNIT_FINISHED,
            job_id=job_id,
            unit_id=unit.unit_id,
            data=payload | {"status": "error"},
        )
        code = (
            getattr(getattr(exc, "code", None), "value", None) or ErrorCode.AGENT_TURN_FAILED.value
        )
        return UnitResult(
            unit_id=unit.unit_id,
            status=UnitStatus.ERROR,
            error_code=str(code),
            plan_epoch=plan_epoch,
        )

    req_ids = tuple(result.debug.req_ids) if result.debug.req_ids else ()
    status = UnitStatus.OK if result.error is None else UnitStatus.ERROR
    err_code = result.error.code if result.error is not None else None
    artifacts: dict[str, Any] = {
        "session_id": result.session.session_id if result.session else None,
    }
    usage = getattr(result.debug, "tokens", None)
    if isinstance(usage, Mapping) and (
        usage.get("ok") or usage.get("prompt") or usage.get("completion") or usage.get("total")
    ):
        artifacts["usage"] = dict(usage)
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
        answer=result.answer,
        req_ids=req_ids,
        artifacts=artifacts,
        error_code=err_code,
        plan_epoch=plan_epoch,
    )
