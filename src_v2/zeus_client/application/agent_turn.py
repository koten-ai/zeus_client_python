"""Agent turn use-case — journaled LLM + Zeus loop (ZCM-004 · ZCP-18).

Loop law (locked):
  setup journal + messages
  loop rounds:
    llm.complete
    tool_calls → zeus hops (pipeline allowed inside agent only) → append tools
    terminate (return | pipeline turn_complete) → cheap vs insight
  policy + peel → answer
  return TurnResult

Session commit / Detective are soft-optional; projectors never raise out of ok turns.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from zeus_client_v2.application.middleware import MiddlewareChain, MiddlewareContext
from zeus_client_v2.application.detective import safe_build_detective_briefing
from zeus_client_v2.application.projectors.public_trace import build_public_trace
from zeus_client_v2.application.projectors.session_trace import select_primary_req_id
from zeus_client_v2.config.models import ClientSettings, DataTarget, DebugPolicy
from zeus_client_v2.domain.errors import ErrorCode, LlmError, ZeusClientError
from zeus_client_v2.domain.journal.events import EVENT_NOTE, EVENT_TURN_COMPLETED, EVENT_TURN_STARTED, JournalEvent
from zeus_client_v2.domain.journal.journal import InMemoryJournal
from zeus_client_v2.domain.layer_a import (
    LayerA,
    parse_layer_a,
    peel_layer_a_summary,
    user_facing_answer,
)
from zeus_client_v2.domain.messages import (
    DebugBundle,
    ErrorInfo,
    StructuredResult,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from zeus_client_v2.domain.policy import decide_policy
from zeus_client_v2.domain.session import SessionHandle
from zeus_client_v2.ports import LlmPort, LlmRequest, VerbHopResult, VerbRequest, ZeusPort

import os

__all__ = [
    "AgentTurnUseCase",
    "ToolRoundOutcome",
    "INSIGHT_AFTER_ZEUS_INSTRUCTION",
    "CHEAP_FINAL_STATIC_ANSWER",
    "run_agent_turn",
]

INSIGHT_AFTER_ZEUS_INSTRUCTION = (
    "Zeus tool results (including row/data payloads) are already in this "
    "conversation. Analyze that evidence and write a clear, useful answer for "
    "the operator: what was found, notable names/counts/patterns, and any "
    "caveats. Do not call tools. Do not re-run the same successful pipeline or "
    "invent rows/fields not present in the tool results. Prefer concrete "
    "details from the data over a one-line abstract summary."
)

CHEAP_FINAL_STATIC_ANSWER = "Zeus returned data. See structured results in the UI."

MAX_TOOLCALLS_PER_ROUND = 8
_TERMINATE_NAMES = frozenset({"return", "return_result"})


@dataclass
class ToolRoundOutcome:
    return_seen: bool = False
    terminal_summary: str | None = None
    tool_arg_summary: str | None = None
    tools_executed: int = 0
    tools_with_data: int = 0
    tools_empty: int = 0
    hops: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    # last return tool args for Layer A parse
    return_args: dict[str, Any] | None = None


def _is_empty_json_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, set)):
        return len(v) == 0
    if isinstance(v, dict):
        if not v:
            return True
        for key in ("rows", "items", "results", "entities"):
            if key in v:
                return _is_empty_json_value(v.get(key))
        data = v.get("data")
        if data is not None:
            return _is_empty_json_value(data)
        result = v.get("result")
        if result is not None and result is not v:
            return _is_empty_json_value(result)
        return False
    return False


def _has_turn_complete(body: Any) -> bool:
    if isinstance(body, Mapping) and body.get("turn_complete") is True:
        return True
    return False


def _summary_from_terminal(body: Any, tc_args: Mapping[str, Any]) -> str:
    if isinstance(body, Mapping):
        for key in ("summary", "answer", "message"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    val = tc_args.get("summary") if isinstance(tc_args, Mapping) else None
    if isinstance(val, str) and val.strip():
        return val.strip()
    return ""


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            obj = json.loads(raw or "{}")
            return dict(obj) if isinstance(obj, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _tools_from_request(req: TurnRequest) -> list[dict[str, Any]]:
    if req.tools:
        return [dict(t) for t in req.tools]
    cr = req.chat_request if isinstance(req.chat_request, Mapping) else {}
    tools = cr.get("tools") if cr else None
    if isinstance(tools, list):
        return [dict(t) for t in tools if isinstance(t, Mapping)]
    return []


def _system_from_request(req: TurnRequest) -> str:
    cr = req.chat_request if isinstance(req.chat_request, Mapping) else {}
    msgs = cr.get("messages") if cr else None
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, Mapping) and m.get("role") == "system":
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    return c
    return req.system_prompt or "You are a helpful Zeus data assistant."


@dataclass
class AgentTurnUseCase:
    """Run one agent turn over injected ports (no process-global HTTP)."""

    llm: LlmPort
    zeus: ZeusPort | None = None
    journal: InMemoryJournal | None = None
    middleware: MiddlewareChain = field(default_factory=MiddlewareChain)
    default_settings: ClientSettings = field(default_factory=ClientSettings)
    debug_policy: DebugPolicy = field(default_factory=DebugPolicy)
    hub_base_url: str | None = None

    async def run(self, req: TurnRequest) -> TurnResult:
        return await run_agent_turn(
            req,
            llm=self.llm,
            zeus=self.zeus,
            journal=self.journal,
            middleware=self.middleware,
            default_settings=self.default_settings,
            debug_policy=self.debug_policy,
            hub_base_url=self.hub_base_url,
        )


async def run_agent_turn(
    req: TurnRequest,
    *,
    llm: LlmPort,
    zeus: ZeusPort | None = None,
    journal: InMemoryJournal | None = None,
    middleware: MiddlewareChain | None = None,
    default_settings: ClientSettings | None = None,
    debug_policy: DebugPolicy | None = None,
    hub_base_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> TurnResult:
    settings = req.settings or default_settings or ClientSettings()
    dbg_pol = debug_policy or DebugPolicy()
    mw = middleware or MiddlewareChain()
    turn_id = f"turn_{uuid.uuid4().hex[:12]}"
    t0 = time.time()
    notes: list[str] = []
    hops: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    mw_ctx = MiddlewareContext(turn_id=turn_id, user_msg=req.message)
    journal = journal or InMemoryJournal()
    finish_kw = {
        "debug_policy": dbg_pol,
        "hub_base_url": hub_base_url,
        "target": req.target,
        "tools": req.tools,
        "chat_request": req.chat_request,
        "env": env,
    }

    def _je(etype: str, data: Mapping[str, Any]) -> None:
        journal.append(
            JournalEvent(
                event_id=f"{etype}_{uuid.uuid4().hex[:10]}",
                ts_ms=int(time.time() * 1000),
                type=etype,
                component="application.agent_turn",
                turn_id=turn_id,
                span_id=None,
                parent_span_id=None,
                data=dict(data),
            )
        )

    _je(EVENT_TURN_STARTED, {"message_preview": (req.message or "")[:200]})

    if not (req.message or "").strip():
        err = ErrorInfo(
            code=ErrorCode.AGENT_MESSAGE_EMPTY.value,
            message="agent message empty",
            component="application.agent_turn",
        )
        return _finish(
            answer="",
            status=TurnStatus.ERROR,
            messages=(),
            settings=settings,
            turn_id=turn_id,
            notes=tuple(notes + ["empty message"]),
            rounds=0,
            hops=(),
            steps=(),
            journal=journal,
            error=err,
            session=req.session,
            layer=None,
            decision=None,
            t0=t0,
            je=_je,
            **finish_kw,
        )

    ai_process = bool(settings.ai_process_result)
    max_rounds = max(1, int(settings.max_rounds or 8))
    if ai_process and max_rounds < 2:
        max_rounds = 2
        notes.append("ai_process_result=true: max_rounds raised to 2 for insight turn")
    notes.append(f"ai_process_result={str(ai_process).lower()}")

    system = _system_from_request(req)
    tools = _tools_from_request(req)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for pm in req.prior_messages:
        if isinstance(pm, Mapping):
            messages.append(dict(pm))
    messages.append({"role": "user", "content": req.message})

    await mw.on_turn_start(mw_ctx)
    notes.extend(mw_ctx.notes)
    mw_ctx.notes.clear()

    answer: str | None = None
    exit_kind: str | None = None
    last_return_args: dict[str, Any] | None = None
    rounds_done = 0

    try:
        for rnd in range(1, max_rounds + 1):
            rounds_done = rnd
            mw_ctx.round = rnd
            await mw.before_llm(mw_ctx, messages)
            notes.extend(mw_ctx.notes)
            mw_ctx.notes.clear()

            try:
                llm_resp = await llm.complete(
                    LlmRequest(
                        messages=tuple(messages),
                        model=req.model,
                        tools=tuple(tools) if tools else (),
                        temperature=0.0,
                        conv_id=req.chat_id,
                    )
                )
            except LlmError as exc:
                err = ErrorInfo(
                    code=exc.code.value,
                    message=exc.public_message,
                    retryable=exc.retryable,
                    component=exc.component,
                    details=dict(exc.details),
                )
                notes.append(f"llm_error: {exc.code.value}")
                return _finish(
                    answer=f"LLM error: {exc.public_message}",
                    status=TurnStatus.ERROR,
                    messages=tuple(messages),
                    settings=settings,
                    turn_id=turn_id,
                    notes=tuple(notes),
                    rounds=rounds_done,
                    hops=tuple(hops),
                    steps=tuple(steps),
                    journal=journal,
                    error=err,
                    session=req.session,
                    layer=None,
                    decision=None,
                    t0=t0,
                    je=_je,
                    ai_exit=None,
                    **finish_kw,
                )

            await mw.after_llm(
                mw_ctx,
                {
                    "content": llm_resp.content,
                    "tool_calls": list(llm_resp.tool_calls),
                    "usage": dict(llm_resp.usage),
                },
            )
            notes.extend(mw_ctx.notes)
            mw_ctx.notes.clear()

            tool_calls = list(llm_resp.tool_calls or ())
            steps.append(
                {
                    "round": rnd,
                    "type": "llm",
                    "tool_calls": [
                        (tc.get("function") or {}).get("name")
                        if isinstance(tc, Mapping)
                        else None
                        for tc in tool_calls
                    ],
                    "usage": dict(llm_resp.usage or {}),
                }
            )

            if not tool_calls:
                answer = (llm_resp.content or "").strip() or "(model returned no content)"
                messages.append({"role": "assistant", "content": answer})
                exit_kind = "direct"
                break

            # assistant with tool_calls
            asst: dict[str, Any] = {
                "role": "assistant",
                "content": llm_resp.content,
                "tool_calls": [dict(tc) for tc in tool_calls if isinstance(tc, Mapping)],
            }
            messages.append(asst)

            if zeus is None:
                notes.append("zeus port missing; cannot execute tools")
                answer = "Zeus port not configured for tool calls"
                exit_kind = "error"
                break

            outcome = await _execute_tool_calls(
                tool_calls=tool_calls,
                messages=messages,
                zeus=zeus,
                target=req.target,
                mode=settings.mode,
                middleware=mw,
                mw_ctx=mw_ctx,
                round_n=rnd,
            )
            hops.extend(outcome.hops)
            steps.extend(outcome.steps)
            notes.extend(mw_ctx.notes)
            mw_ctx.notes.clear()
            if outcome.return_args is not None:
                last_return_args = outcome.return_args

            if outcome.return_seen:
                terminal = (outcome.terminal_summary or "").strip()
                if ai_process:
                    synth = await _insight_hop(
                        llm=llm,
                        messages=messages,
                        model=req.model,
                        chat_id=req.chat_id,
                        notes=notes,
                        steps=steps,
                        round_n=rnd,
                    )
                    answer = (synth or terminal or "").strip()
                    exit_kind = "insight"
                    notes.append(
                        "ai_process_result=true after terminating Zeus tool; insight synthesis"
                    )
                else:
                    answer = terminal
                    if answer and not _recent_assistant_has(messages, answer):
                        messages.append({"role": "assistant", "content": answer})
                    exit_kind = "cheap_terminal"
                    notes.append(
                        "ai_process_result=false after terminate; cheap terminal envelope"
                    )
                break

            if (
                not ai_process
                and outcome.tools_executed > 0
                and outcome.tools_with_data > 0
            ):
                answer = (
                    (outcome.tool_arg_summary or "").strip() or CHEAP_FINAL_STATIC_ANSWER
                )
                if not _recent_assistant_has(messages, answer):
                    messages.append({"role": "assistant", "content": answer})
                exit_kind = "cheap_final"
                notes.append(
                    "ai_process_result=false after Zeus data; thin final without second LLM hop"
                )
                break
            # continue multi-round
        else:
            answer = "Ran out of tool rounds before the model produced a final answer."
            exit_kind = "max_rounds"
            notes.append("max_rounds exceeded")

    except ZeusClientError as exc:
        err = ErrorInfo(
            code=exc.code.value,
            message=exc.public_message,
            retryable=exc.retryable,
            component=exc.component,
            details=dict(exc.details),
        )
        notes.append(f"turn_error: {exc.code.value}")
        return _finish(
            answer=answer or exc.public_message,
            status=TurnStatus.ERROR,
            messages=tuple(messages),
            settings=settings,
            turn_id=turn_id,
            notes=tuple(notes),
            rounds=rounds_done,
            hops=tuple(hops),
            steps=tuple(steps),
            journal=journal,
            error=err,
            session=req.session,
            layer=None,
            decision=None,
            t0=t0,
            je=_je,
            ai_exit=exit_kind,
            **finish_kw,
        )

    # Layer A + policy when terminate bag present
    layer: LayerA | None = None
    if last_return_args is not None:
        layer = parse_layer_a(
            last_return_args,
            allow_array_triggers=settings.allow_array_triggers,
            output_request=settings.output_request,
            app_output_on_error=settings.app_output_on_error,
        )
    decision = decide_policy(layer, settings=settings) if layer is not None else None

    raw_answer = answer or ""
    # Insight/model may echo a full Layer A dump — peel summary first so G2
    # never lands in chat; bag summary is fallback, not preferred over peel.
    peeled = peel_layer_a_summary(raw_answer)
    if peeled:
        final_answer = peeled
    else:
        final_answer = user_facing_answer(
            raw_answer,
            layer_summary=layer.summary if layer else None,
        )
    if decision is not None:
        if decision.forced and decision.policy in ("refuse", "error"):
            final_answer = decision.ui_text or final_answer
        elif not (final_answer or "").strip():
            final_answer = decision.ui_text or final_answer
        elif decision.policy == "clarify" and decision.ui_text:
            final_answer = decision.ui_text


    # Belt: never leave G2 markers if peel missed
    if "wish_i_knew" in final_answer and layer is not None and layer.summary:
        final_answer = layer.summary

    await mw.on_turn_end(mw_ctx, final_answer)
    notes.extend(mw_ctx.notes)

    if exit_kind == "max_rounds":
        status = TurnStatus.MAX_ROUNDS
    elif decision and decision.policy == "refuse":
        status = TurnStatus.REFUSED
    elif decision and decision.policy == "clarify":
        status = TurnStatus.CLARIFY
    elif decision and decision.policy == "error":
        status = TurnStatus.ERROR
    else:
        status = TurnStatus.OK

    return _finish(
        answer=final_answer,
        status=status,
        messages=tuple(messages),
        settings=settings,
        turn_id=turn_id,
        notes=tuple(notes),
        rounds=rounds_done,
        hops=tuple(hops),
        steps=tuple(steps),
        journal=journal,
        error=None,
        session=req.session,
        layer=layer,
        decision=decision,
        t0=t0,
        je=_je,
        ai_exit=exit_kind,
        **finish_kw,
    )


def _recent_assistant_has(messages: Sequence[Mapping[str, Any]], content: str) -> bool:
    for m in list(messages)[-3:]:
        if m.get("role") == "assistant" and m.get("content") == content:
            return True
    return False


async def _insight_hop(
    *,
    llm: LlmPort,
    messages: list[dict[str, Any]],
    model: str | None,
    chat_id: str | None,
    notes: list[str],
    steps: list[dict[str, Any]],
    round_n: int,
) -> str:
    messages.append({"role": "user", "content": INSIGHT_AFTER_ZEUS_INSTRUCTION})
    notes.append("force_final: ai_process_result_insight")
    try:
        resp = await llm.complete(
            LlmRequest(
                messages=tuple(messages),
                model=model,
                tools=(),  # no tools
                temperature=0.0,
                conv_id=chat_id,
            )
        )
    except LlmError as exc:
        notes.append(f"insight_failed: {exc.code.value}")
        return ""
    content = (resp.content or "").strip()
    if content:
        messages.append({"role": "assistant", "content": content})
        steps.append(
            {
                "round": round_n,
                "type": "force_final",
                "cause": "ai_process_result_insight",
                "content_len": len(content),
            }
        )
    else:
        notes.append("force_final_empty: ai_process_result_insight")
    return content


async def _execute_tool_calls(
    *,
    tool_calls: Sequence[Mapping[str, Any]],
    messages: list[dict[str, Any]],
    zeus: ZeusPort,
    target: DataTarget,
    mode: str,
    middleware: MiddlewareChain,
    mw_ctx: MiddlewareContext,
    round_n: int,
) -> ToolRoundOutcome:
    outcome = ToolRoundOutcome()
    final_summary: str | None = None
    return_seen = False

    for tc in list(tool_calls)[:MAX_TOOLCALLS_PER_ROUND]:
        if not isinstance(tc, Mapping):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), Mapping) else {}
        name = str((fn or {}).get("name") or "")
        tc_args = _parse_tool_args((fn or {}).get("arguments"))
        call_id = str(tc.get("id") or f"call_{round_n}_{outcome.tools_executed}")

        if isinstance(tc_args.get("summary"), str) and tc_args["summary"].strip():
            outcome.tool_arg_summary = tc_args["summary"].strip()

        if name in _TERMINATE_NAMES:
            final_summary = str(tc_args.get("summary") or "")
            return_seen = True
            outcome.return_args = dict(tc_args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(tc_args),
                }
            )
            outcome.steps.append({"round": round_n, "type": name, "args": tc_args})
            continue

        tc_args = await middleware.before_zeus(mw_ctx, name, tc_args)
        if isinstance(tc_args.get("summary"), str) and tc_args["summary"].strip():
            outcome.tool_arg_summary = tc_args["summary"].strip()

        t_tool = time.perf_counter()
        hop = await zeus.call_verb(
            VerbRequest(
                verb=name,
                body=tc_args,
                target=target,
                mode_header=mode or "analytics",
                allow_pipeline=True,
            )
        )
        ms = int((time.perf_counter() - t_tool) * 1000)
        body = hop.body if isinstance(hop.body, Mapping) else {}
        text = json.dumps(body) if body else (hop.error or "")
        await middleware.after_zeus(mw_ctx, name, hop.status_code, body or text)

        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": text,
            }
        )
        hop_rec = {
            "req_id": hop.req_id,
            "name": name,
            "status": hop.status_code,
            "ok": hop.ok,
            "ms": ms,
            "snippet": text[:500],
        }
        outcome.hops.append(hop_rec)
        outcome.steps.append(
            {
                "round": round_n,
                "type": "tool",
                "name": name,
                "args": tc_args,
                "status": hop.status_code,
                "ms": ms,
                "req_id": hop.req_id,
            }
        )
        outcome.tools_executed += 1
        empty = (not hop.ok) or _is_empty_json_value(body) or not text.strip()
        if empty:
            outcome.tools_empty += 1
        else:
            outcome.tools_with_data += 1

        if name == "pipeline" and _has_turn_complete(body):
            return_seen = True
            if not final_summary:
                final_summary = _summary_from_terminal(body, tc_args)
            # Only treat as Layer A bag when required-four-shaped (not bare pipeline).
            cand = dict(tc_args) if isinstance(tc_args, dict) else {}
            if isinstance(body, Mapping):
                for k in (
                    "summary",
                    "query_decomposition",
                    "decomposition",
                    "confidence",
                    "policy_action",
                ):
                    if k not in cand and k in body:
                        cand[k] = body[k]
            if (
                isinstance(cand.get("summary"), str)
                and isinstance(cand.get("query_decomposition"), dict)
                and isinstance(cand.get("decomposition"), dict)
                and isinstance(cand.get("confidence"), str)
            ):
                outcome.return_args = cand


    outcome.return_seen = return_seen
    outcome.terminal_summary = final_summary if return_seen else None
    return outcome


def _finish(
    *,
    answer: str,
    status: TurnStatus,
    messages: tuple[Mapping[str, Any], ...],
    settings: ClientSettings,
    turn_id: str,
    notes: tuple[str, ...],
    rounds: int,
    hops: tuple[Mapping[str, Any], ...],
    steps: tuple[Mapping[str, Any], ...],
    journal: InMemoryJournal,
    error: ErrorInfo | None,
    session: SessionHandle | None,
    layer: LayerA | None,
    decision: Any,
    t0: float,
    je: Any,
    ai_exit: str | None = None,
    debug_policy: DebugPolicy | None = None,
    hub_base_url: str | None = None,
    target: DataTarget | None = None,
    tools: tuple[Mapping[str, Any], ...] = (),
    chat_request: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> TurnResult:
    structured: StructuredResult | None = None
    layer_map: dict[str, Any] | None = None
    if layer is not None:
        layer_map = {
            "ok": layer.ok,
            "summary": layer.summary,
            "confidence": layer.confidence,
            "policy_action": layer.policy_action,
            "errors": list(layer.errors),
            "warnings": list(layer.warnings),
        }
        if decision is not None:
            structured = StructuredResult(
                layer_a=layer_map,
                policy=decision.policy,
                flags=dict(decision.flags),
                ui=decision.ui(layer),
                artifacts=decision.artifacts(layer),
                policy_reason=decision.reason,
            )
        else:
            structured = StructuredResult(layer_a=layer_map)

    public = build_public_trace(
        turn_id=turn_id,
        answer=answer,
        status=status.value,
        rounds=rounds,
        notes=notes,
        hops=hops,
        ai_process_result=bool(settings.ai_process_result),
        ai_process_result_exit=ai_exit,
        layer_a=layer_map,
        policy=decision.policy if decision else None,
        flags=decision.flags if decision else {},
        steps=steps,
    )
    # G2 never in answer
    if "wish_i_knew" in answer:
        answer = (layer.summary if layer and layer.summary else answer.split("wish_i_knew")[0]).strip()

    total_ms = int((time.time() - t0) * 1000)
    pref: str | None = None
    try:
        pref = select_primary_req_id(list(hops))
    except Exception:
        pref = None

    detective = None
    det_notes = list(notes)
    try:
        tgt = target
        target_map = None
        if tgt is not None:
            target_map = {
                "bucket": tgt.bucket,
                "scope": tgt.scope,
                "collection": tgt.collection,
                "mode": settings.mode,
            }
        catalog = dict(chat_request) if isinstance(chat_request, Mapping) else None
        det = safe_build_detective_briefing(
            enabled=(debug_policy or DebugPolicy()).detective_briefing,
            env=env,
            turn_id=turn_id,
            answer=answer,
            status=status.value,
            rounds=rounds,
            hops=hops,
            notes=notes,
            messages=messages,
            catalog=catalog,
            tools=tools,
            layer_a=layer_map,
            total_ms=total_ms,
            hub_base_url=hub_base_url,
            session_id=session.session_id if session else None,
            target=target_map,
            contract_status=session.contract_status if session else None,
            ai_process_result=bool(settings.ai_process_result),
            ai_process_result_exit=ai_exit,
            public_trace=public,
        )
        if det is None and (debug_policy or DebugPolicy()).detective_briefing:
            # distinguish kill-switch vs builder failure only loosely
            if str((env or os.environ).get("ZEUS_CLIENT_DETECTIVE", "1")).lower() in {
                "0",
                "false",
                "no",
                "off",
            } or not (debug_policy or DebugPolicy()).detective_briefing:
                pass
            else:
                # enabled but None → soft fail inside safe_build swallowed exception
                # only note when we expected a briefing (enabled)
                pass
        detective = det
        if detective is None:
            # If kill-switch off, stay silent; if on and failed, note.
            enabled_flag = (debug_policy or DebugPolicy()).detective_briefing
            env_on = str((env or os.environ).get("ZEUS_CLIENT_DETECTIVE", "1")).lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
            if enabled_flag and env_on and answer is not None:
                # Builder returned None unexpectedly only on exception; kill-switch also None.
                # We cannot distinguish easily — safe_build returns None for both.
                pass
    except Exception as exc:  # noqa: BLE001
        det_notes.append(f"detective_briefing_failed: {exc}")
        detective = None

    if detective and "wish_i_knew" in str(detective.get("overview", {}).get("answer_preview", "")):
        # belt — overview preview already from peeled answer
        pass

    # Put detective on public_trace for widget consumers
    if detective is not None:
        public = dict(public)
        public["detective"] = detective

    pref_final = pref
    if pref_final is None and isinstance(detective, Mapping):
        ov = detective.get("overview")
        if isinstance(ov, Mapping):
            pref_final = ov.get("preferred_req_id")  # type: ignore[assignment]

    debug = DebugBundle(
        turn_id=turn_id,
        notes=tuple(det_notes),
        rounds=rounds,
        ai_process_result=bool(settings.ai_process_result),
        ai_process_result_exit=ai_exit,
        public_trace=public,
        hops=hops,
        journal_event_count=len(journal.events()),
        hooks_jailbreak_score=float(decision.hooks_jailbreak_score) if decision else 0.0,
        detective=detective,
        preferred_req_id=pref_final if isinstance(pref_final, str) or pref_final is None else str(pref_final),
    )
    try:
        je(
            EVENT_TURN_COMPLETED,
            {
                "status": status.value,
                "rounds": rounds,
                "ai_process_result_exit": ai_exit,
                "total_ms": total_ms,
                "answer_preview": (answer or "")[:240],
                "detective": bool(detective),
            },
        )
    except Exception:
        pass

    return TurnResult(
        answer=answer,
        status=status,
        structured=structured,
        session=session,
        debug=debug,
        error=error,
        messages=messages,
        layer_a=layer,
        policy=decision,
    )
