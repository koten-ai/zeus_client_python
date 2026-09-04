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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from zeus_client.adapters.zeus_http.headers import (
    TRACE_CLASS_AGENT,
    TRACE_CLASS_SESSION,
    correlation_headers,
    verb_body_without_rewind,
)
from zeus_client.application.control_plane_inject import (
    InjectSettings,
    apply_control_plane_inject,
    apply_tool_path_inject,
    prepare_settings,
)
from zeus_client.application.detective import safe_build_detective_briefing
from zeus_client.application.detective.extract import (
    catalog_flags_of,
    collect_req_ids,
    inject_for_session_trace,
    inject_slice_sha12s,
    system_prompt_of,
    tool_payload_shape,
)
from zeus_client.application.middleware import (
    MiddlewareChain,
    MiddlewareContext,
    SecurityHooks,
    inspect_jailbreak,
)
from zeus_client.application.projectors.public_trace import build_public_trace
from zeus_client.application.projectors.session_trace import (
    TRACE_SNIPPET_MAX,
    extract_pipeline_meta,
    project_session_trace,
    select_primary_req_id,
)
from zeus_client.application.semantic_cache import (
    hop_from_memory,
    isolation_user_id,
    recall_and_inject,
    write_memory_block,
)
from zeus_client.application.tokens import sum_provider_tokens, tokens_for_session_trace
from zeus_client.config.models import (
    ClientSettings,
    DataTarget,
    DebugPolicy,
    SemanticCacheConfig,
)
from zeus_client.domain.errors import ErrorCode, LlmError, ZeusClientError
from zeus_client.domain.ids import new_trace_id, new_zeus_req_id
from zeus_client.domain.journal.events import (
    EVENT_TURN_COMPLETED,
    EVENT_TURN_STARTED,
    JournalEvent,
)
from zeus_client.domain.journal.journal import InMemoryJournal
from zeus_client.domain.layer_a import (
    LayerA,
    apply_pack_schema,
    compact_layer_a,
    parse_layer_a,
    parse_pipeline_envelope,
    peel_layer_a_summary,
    user_facing_answer,
)
from zeus_client.domain.messages import (
    DebugBundle,
    ErrorInfo,
    StructuredResult,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from zeus_client.domain.policy import decide_policy
from zeus_client.domain.session import SessionHandle
from zeus_client.domain.stamps import product_stamp, resolve_client_ip
from zeus_client.domain.tool_trail import (
    render_trail_inject,
    trail_entry_from_hop,
    upsert_trail_on_system,
)
from zeus_client.observability.logging import get_family_logger
from zeus_client.observability.metrics import MetricsPort
from zeus_client.ports import AgentMemoryPort, LlmPort, LlmRequest, VerbRequest, ZeusPort
from zeus_client.ports.id_factory import IdFactory

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
_ORIENTATION_VERBS = frozenset({"describe", "explain"})


@dataclass
class ToolRoundOutcome:
    return_seen: bool = False
    terminal_summary: str | None = None
    tool_arg_summary: str | None = None
    tools_executed: int = 0
    tools_with_data: int = 0
    tools_with_payload: int = 0
    tools_empty: int = 0
    hops: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    # last return tool args for Layer A parse
    return_args: dict[str, Any] | None = None
    terminate_via: str | None = None


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
    if isinstance(tools, list) and tools:
        return [dict(t) for t in tools if isinstance(t, Mapping)]
    verbs = cr.get("verbs") if cr else None
    if isinstance(verbs, list):
        return [dict(t) for t in verbs if isinstance(t, Mapping)]
    return []


def _catalog_tool_names(tools: Sequence[Mapping[str, Any]]) -> set[str]:
    names: set[str] = set()
    for t in tools:
        if not isinstance(t, Mapping):
            continue
        fn = t.get("function") if isinstance(t.get("function"), Mapping) else t
        if isinstance(fn, Mapping) and fn.get("name"):
            names.add(str(fn["name"]))
    return names


def _synthetic_pipeline_call(args: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": new_zeus_req_id(),
        "type": "function",
        "function": {"name": "pipeline", "arguments": json.dumps(dict(args))},
    }


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
    agent_memory: AgentMemoryPort | None = None
    semantic_cache: SemanticCacheConfig | None = None
    auth_mode: str = "none"
    metrics: MetricsPort | None = None

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
            agent_memory=self.agent_memory,
            semantic_cache=self.semantic_cache,
            auth_mode=self.auth_mode,
            metrics=self.metrics,
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
    session_lifecycle: Any = None,
    zeus_url: str | None = None,
    client_floor: str | None = None,
    extra_notes: Sequence[str] = (),
    ids: IdFactory | None = None,
    client_ip: str | None = None,
    agent_memory: AgentMemoryPort | None = None,
    semantic_cache: SemanticCacheConfig | None = None,
    auth_mode: str = "none",
    metrics: MetricsPort | None = None,
) -> TurnResult:
    settings = prepare_settings(req.settings or default_settings or ClientSettings())
    sc = req.semantic_cache or semantic_cache or SemanticCacheConfig()
    dbg_pol = debug_policy or DebugPolicy()
    mw = middleware or MiddlewareChain(items=[SecurityHooks()])
    chat_req: dict[str, Any] = (
        dict(req.chat_request) if isinstance(req.chat_request, Mapping) else {}
    )
    if chat_req:
        chat_req = apply_control_plane_inject(
            chat_req, InjectSettings.from_client_settings(settings)
        )
        chat_req = apply_tool_path_inject(
            chat_req, ignore=bool(settings.ignore_user_tool_path_hints)
        )
        req = TurnRequest(
            message=req.message,
            target=req.target,
            settings=settings,
            session=req.session,
            prior_messages=req.prior_messages,
            system_prompt=req.system_prompt,
            tools=req.tools,
            chat_request=chat_req,
            base_id=req.base_id,
            pack_schema=req.pack_schema,
            chat_id=req.chat_id,
            model=req.model,
            enable_sessions=req.enable_sessions,
        )
    turn_id = ids.turn_id() if ids is not None else new_zeus_req_id()
    chat_id = (req.chat_id or "").strip() or (
        ids.chat_id() if ids is not None else new_zeus_req_id()
    )
    trace_id = new_trace_id()
    t0 = time.time()
    log = get_family_logger()
    stamp = product_stamp(
        ip_address=resolve_client_ip(client_ip, probe_host=False),
        scope=f"{req.target.bucket}/{req.target.scope}" if req.target.bucket else "",
    )
    notes: list[str] = [n for n in extra_notes if n]
    hops: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    mw_ctx = MiddlewareContext(turn_id=turn_id, user_msg=req.message)
    journal = journal or InMemoryJournal()
    finish_kw = {
        "debug_policy": dbg_pol,
        "hub_base_url": hub_base_url,
        "target": req.target,
        "tools": (),
        "chat_request": req.chat_request,
        "env": env,
        "chat_id": chat_id,
        "zeus_url": zeus_url,
        "client_floor": client_floor or "client-floor-5",
        "base_id": req.base_id,
        "hooks_score": 0.0,
        "stamp": stamp,
        "trace_id": trace_id,
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

    _je(
        EVENT_TURN_STARTED,
        {
            "message_preview": (req.message or "")[:200],
            "base_id": req.base_id,
            "client_floor": client_floor or "client-floor-5",
            "trace_id": trace_id,
            "chat_id": chat_id,
        },
    )
    scope = f"{req.target.bucket}/{req.target.scope}" if req.target.bucket else ""
    log.info(
        "zeus_client.turn.started",
        **{
            "chat.id": chat_id,
            "turn.id": turn_id,
            "scope": scope,
            "mode": settings.mode,
            "zeus.url": zeus_url or "",
            "trace_id": trace_id,
        },
    )

    session_handle = req.session
    setup_sys = system_prompt_of(
        catalog=req.chat_request if isinstance(req.chat_request, Mapping) else None,
        system_prompt=req.system_prompt,
    )
    setup_brief, setup_mini = inject_slice_sha12s(inject_for_session_trace(system=setup_sys))
    if req.enable_sessions and session_lifecycle is not None:
        try:
            session_handle = await session_lifecycle.setup(
                chat_request=req.chat_request or {},
                user_message=req.message,
                prior=req.session,
                chat_id=chat_id,
                turn_id=turn_id,
                mode=settings.mode,
                enable_sessions=True,
                force_trace=bool(settings.force_trace),
                rewind=bool(dbg_pol.rewind),
                brief_sha12=setup_brief,
                mini_sha12=setup_mini,
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"session_setup_failed: {exc}")
            session_handle = req.session

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
            session=session_handle,
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
    finish_kw["tools"] = tuple(tools)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for pm in req.prior_messages:
        if isinstance(pm, Mapping):
            messages.append(dict(pm))
    messages.append({"role": "user", "content": req.message})

    probe_available: bool | None = None
    if sc.enabled and agent_memory is not None:
        avail_fn = getattr(agent_memory, "available", None)
        if callable(avail_fn):
            try:
                probe_available = bool(await avail_fn())
            except Exception:  # noqa: BLE001
                probe_available = False
                notes.append("semantic_cache.probe: unavailable")
    mem_user = isolation_user_id(sc, auth_mode)
    rec_result, rec_snippet = await recall_and_inject(
        agent_memory,
        sc,
        messages,
        req.message,
        mode="agent",
        headers=correlation_headers(
            chat_id=chat_id,
            turn_id=turn_id,
            mode=settings.mode,
            force_trace=bool(settings.force_trace),
            trace_class=TRACE_CLASS_AGENT,
        ),
        user_id=mem_user,
        target=req.target,
        metrics=metrics,
        probe_available=probe_available,
    )
    if rec_result.skipped:
        if rec_result.skip_reason not in {"disabled", "mode", "recall_disabled", "min_query_chars"}:
            notes.append(f"semantic_cache.recall: skipped={rec_result.skip_reason}")
    elif rec_result.ok:
        notes.append(f"semantic_cache.recall: blocks={len(rec_result.blocks)}")
        hops.append(hop_from_memory(name="agent_memory.recall", result=rec_result))
    else:
        notes.append(
            f"semantic_cache.recall: fail={rec_result.skip_reason or rec_result.error or 'error'}"
        )
        if rec_result.url or rec_result.req_id:
            hops.append(hop_from_memory(name="agent_memory.recall", result=rec_result))
        if sc.recall.fail_closed:
            err = ErrorInfo(
                code=ErrorCode.AGENT_MEMORY_RECALL_FAILED.value,
                message="agent memory recall failed",
                retryable=True,
                component="application.agent_turn",
            )
            return _finish(
                answer="",
                status=TurnStatus.ERROR,
                messages=tuple(messages),
                settings=settings,
                turn_id=turn_id,
                notes=tuple(notes),
                rounds=0,
                hops=tuple(hops),
                steps=(),
                journal=journal,
                error=err,
                session=session_handle,
                layer=None,
                decision=None,
                t0=t0,
                je=_je,
                **finish_kw,
            )

    mw_ctx.data["catalog_tool_names"] = _catalog_tool_names(tools)
    mw_ctx.data["prior_user_texts"] = [
        str(pm.get("content") or "")
        for pm in req.prior_messages
        if isinstance(pm, Mapping) and str(pm.get("role") or "") == "user"
    ]
    await mw.on_turn_start(mw_ctx)
    notes.extend(mw_ctx.notes)
    mw_ctx.notes.clear()
    if mw_ctx.data.get("jailbreak_hits"):
        notes.append("jailbreak.hits=" + ",".join(str(h) for h in mw_ctx.data["jailbreak_hits"]))

    answer: str | None = None
    exit_kind: str | None = None
    last_return_args: dict[str, Any] | None = None
    last_terminate_via: str = "client_terminate"
    rounds_done = 0
    trail: list[dict[str, Any]] = []
    skip_loop = bool(mw_ctx.data.get("hooks_must_refuse"))
    if skip_loop:
        notes.append("jailbreak.pre_llm_refuse")
        answer = ""
        exit_kind = "hooks_refuse"

    hop_inject = inject_for_session_trace(
        system=system_prompt_of(
            messages=messages,
            catalog=req.chat_request if isinstance(req.chat_request, Mapping) else None,
        ),
        catalog=req.chat_request if isinstance(req.chat_request, Mapping) else None,
        rewind=bool(dbg_pol.rewind),
    )
    brief_sha12, mini_sha12 = inject_slice_sha12s(hop_inject)
    chat_session_id = ""
    if session_handle and session_handle.enabled and session_handle.session_id:
        chat_session_id = str(session_handle.session_id)

    try:
        for rnd in range(1, max_rounds + 1):
            if skip_loop:
                break
            rounds_done = rnd
            mw_ctx.round = rnd
            force_left = settings.force_return_rounds_left
            remaining = max_rounds - rnd
            if force_left is not None and remaining <= int(force_left) and rnd > 1:
                notes.append(f"force_return: remaining={remaining} <= {force_left}")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "SYSTEM: Round budget nearly exhausted. "
                            "Terminate now with the return tool (required four fields)."
                        ),
                    }
                )
            if trail and settings.tool_trail_enabled and settings.tool_trail_inject:
                snippet = render_trail_inject(
                    trail, max_entries=int(settings.tool_trail_max_entries or 16)
                )
                upsert_trail_on_system(messages, snippet)
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
                        conv_id=chat_id,
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
                steps.append(
                    {
                        "round": rnd,
                        "type": "llm_error",
                        "code": exc.code.value,
                    }
                )
                if (
                    hops
                    and req.enable_sessions
                    and session_lifecycle is not None
                    and session_handle
                    and session_handle.session_id
                ):
                    try:
                        await project_session_trace(
                            session_lifecycle.client,
                            handle=session_handle,
                            hops=hops,
                            chat_request=req.chat_request or {},
                            inject=inject_for_session_trace(
                                system=system_prompt_of(
                                    messages=messages,
                                    catalog=(
                                        req.chat_request
                                        if isinstance(req.chat_request, Mapping)
                                        else None
                                    ),
                                ),
                                catalog=(
                                    req.chat_request
                                    if isinstance(req.chat_request, Mapping)
                                    else None
                                ),
                                rewind=bool(dbg_pol.rewind),
                            ),
                            tokens=tokens_for_session_trace(steps=steps),
                            stamp=stamp,
                            mode=settings.mode,
                            rewind=bool(dbg_pol.rewind),
                            turn_id=turn_id,
                            headers=correlation_headers(
                                chat_id=chat_id,
                                turn_id=turn_id,
                                force_trace=bool(settings.force_trace),
                                trace_class=TRACE_CLASS_SESSION,
                                chat_session_id=chat_session_id,
                                brief_sha12=brief_sha12,
                                mini_sha12=mini_sha12,
                            ),
                        )
                    except Exception as join_exc:  # noqa: BLE001
                        notes.append(f"session_trace_failed: {join_exc}")
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
                    session=session_handle,
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
            if not tool_calls:
                envelope = parse_pipeline_envelope(llm_resp.content)
                if (
                    envelope
                    and zeus is not None
                    and "pipeline" in _catalog_tool_names(tools)
                    and not mw_ctx.data.get("hooks_must_refuse")
                ):
                    tool_calls = [_synthetic_pipeline_call(envelope)]
                    notes.append(
                        "recovered pipeline envelope from model content as pipeline tool call"
                    )
            steps.append(
                {
                    "round": rnd,
                    "type": "llm",
                    "tool_calls": [
                        (tc.get("function") or {}).get("name") if isinstance(tc, Mapping) else None
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
                chat_id=chat_id,
                turn_id=turn_id,
                force_trace=bool(settings.force_trace),
                rewind=bool(dbg_pol.rewind),
                chat_session_id=chat_session_id,
                brief_sha12=brief_sha12,
                mini_sha12=mini_sha12,
            )
            hops.extend(outcome.hops)
            for hop in outcome.hops:
                empty = bool(hop.get("ok")) and _is_empty_json_value(hop.get("snippet"))
                trail.append(trail_entry_from_hop(hop, seq=len(trail) + 1, empty=empty))
            steps.extend(outcome.steps)
            notes.extend(mw_ctx.notes)
            mw_ctx.notes.clear()
            if outcome.return_args is not None:
                last_return_args = outcome.return_args
            if outcome.terminate_via:
                last_terminate_via = outcome.terminate_via
            if mw_ctx.data.get("jailbreak_hits"):
                note = "jailbreak.hits=" + ",".join(str(h) for h in mw_ctx.data["jailbreak_hits"])
                if note not in notes:
                    notes.append(note)

            if outcome.return_seen:
                terminal = (outcome.terminal_summary or "").strip()
                if ai_process:
                    synth = await _insight_hop(
                        llm=llm,
                        messages=messages,
                        model=req.model,
                        chat_id=chat_id,
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
                    notes.append("ai_process_result=false after terminate; cheap terminal envelope")
                break

            if not ai_process and outcome.tools_with_payload > 0:
                candidate = (outcome.tool_arg_summary or "").strip()
                inspect_jailbreak(mw_ctx, candidate, surface="tool_arg_summary")
                if mw_ctx.data.get("hooks_must_refuse"):
                    notes.append("jailbreak.cheap_path_leak")
                    answer = ""
                    exit_kind = "hooks_refuse"
                    break
                answer = candidate or CHEAP_FINAL_STATIC_ANSWER
                if not _recent_assistant_has(messages, answer):
                    messages.append({"role": "assistant", "content": answer})
                exit_kind = "cheap_final"
                notes.append(
                    "ai_process_result=false after Zeus data; thin final without second LLM hop"
                )
                break
            if mw_ctx.data.get("hooks_must_refuse"):
                notes.append("jailbreak.abort_turn")
                answer = answer or ""
                exit_kind = "hooks_refuse"
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
            session=session_handle,
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
        rule_ids = list((settings.rules or {}).keys()) or None
        layer = parse_layer_a(
            last_return_args,
            rule_ids=rule_ids,
            output_request=settings.output_request,
            app_output_on_error=settings.app_output_on_error,
        )
        apply_pack_schema(layer, req.pack_schema)
        missing = [e.split()[2] if "required field" in e else e for e in (layer.errors or ())]
        get_family_logger().info(
            "zeus_client.layer_a.validated",
            **{"result": "ok" if not layer.errors else "fail", "missing": missing},
        )
        if layer.errors:
            get_family_logger().error(
                "zeus_client.layer_a.invalid",
                **{"result": "fail", "error.type": "parse", "missing": missing},
            )
        inspect_jailbreak(mw_ctx, layer.summary, surface="summary")
    raw_answer = answer or ""
    # Insight/model may echo a full Layer A dump — peel summary first so G2
    # never lands in chat; bag summary is fallback, not preferred over peel.
    peeled = peel_layer_a_summary(raw_answer)
    if peeled:
        pre_policy_answer = peeled
    else:
        pre_policy_answer = user_facing_answer(
            raw_answer,
            layer_summary=layer.summary if layer else None,
        )
    inspect_jailbreak(mw_ctx, pre_policy_answer, surface="answer")
    hooks_score = float(mw_ctx.data.get("hooks_jailbreak_score") or 0.0)
    finish_kw["hooks_score"] = hooks_score
    hooks_refuse = bool(mw_ctx.data.get("hooks_must_refuse"))
    if hooks_refuse and layer is None:
        layer = LayerA(summary="", errors=["hooks_must_refuse"])
    decision = (
        decide_policy(
            layer,
            settings=settings,
            hooks_jailbreak_score=hooks_score,
            hooks_must_refuse=hooks_refuse,
            brand_inject_present=bool(settings.company_context),
        )
        if layer is not None
        else None
    )
    if decision is not None:
        get_family_logger().info(
            "zeus_client.policy.applied",
            **{"policy_action": decision.policy, "result": "ok"},
        )

    final_answer = pre_policy_answer
    if decision is not None:
        if (
            decision.forced
            and decision.policy in ("refuse", "error")
            or not (final_answer or "").strip()
        ):
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

    inject_bag = inject_for_session_trace(
        system=system_prompt_of(
            messages=messages,
            catalog=req.chat_request if isinstance(req.chat_request, Mapping) else None,
        ),
        catalog=req.chat_request if isinstance(req.chat_request, Mapping) else None,
        rewind=bool(dbg_pol.rewind),
    )
    post_brief, post_mini = inject_slice_sha12s(inject_bag)

    if (
        req.enable_sessions
        and session_lifecycle is not None
        and session_handle
        and session_handle.session_id
    ):
        compact = None
        if layer is not None:
            compact = compact_layer_a(layer, via=last_terminate_via)
        try:
            await project_session_trace(
                session_lifecycle.client,
                handle=session_handle,
                hops=hops,
                chat_request=req.chat_request or {},
                layer_a=compact,
                inject=inject_bag,
                tokens=tokens_for_session_trace(steps=steps),
                stamp=stamp,
                mode=settings.mode,
                rewind=bool(dbg_pol.rewind),
                turn_id=turn_id,
                headers=correlation_headers(
                    chat_id=chat_id,
                    turn_id=turn_id,
                    force_trace=bool(settings.force_trace),
                    trace_class=TRACE_CLASS_SESSION,
                    chat_session_id=chat_session_id,
                    brief_sha12=post_brief,
                    mini_sha12=post_mini,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"session_trace_failed: {exc}")
        try:
            commit = await session_lifecycle.commit(
                session_handle,
                chat_request=req.chat_request or {},
                produced_delta=messages,
                mode=settings.mode,
                turn_id=turn_id,
                force_trace=bool(settings.force_trace),
                rewind=bool(dbg_pol.rewind),
                brief_sha12=post_brief,
                mini_sha12=post_mini,
            )
            session_handle = commit.handle
        except Exception as exc:  # noqa: BLE001
            notes.append(f"session_commit_failed: {exc}")

    write_headers = correlation_headers(
        chat_id=chat_id,
        turn_id=turn_id,
        mode=settings.mode,
        force_trace=bool(settings.force_trace),
        trace_class=TRACE_CLASS_AGENT,
    )
    sid = session_handle.session_id if session_handle and session_handle.session_id else None
    auto_writes = 0
    max_auto = max(0, int(sc.write.max_blocks_per_turn or 0))
    if sc.write.write_user_message and auto_writes < max_auto:
        wr = await write_memory_block(
            agent_memory,
            sc,
            req.message,
            mode="agent",
            block_type=sc.write.default_type,
            headers=write_headers,
            user_id=mem_user,
            zeus_session_id=sid,
            target=req.target,
            metrics=metrics,
            explicit=False,
            probe_available=probe_available,
        )
        if wr.skipped:
            if wr.skip_reason not in {
                "disabled",
                "mode",
                "write_disabled",
                "write_explicit_only",
                "on_turn_commit",
                "min_chars",
            }:
                notes.append(f"semantic_cache.write: skipped={wr.skip_reason}")
        elif wr.ok:
            auto_writes += 1
            hops.append(hop_from_memory(name="agent_memory.write", result=wr))
            notes.append("semantic_cache.write: user_message")
        else:
            notes.append(f"semantic_cache.write: fail={wr.error or wr.skip_reason}")
            if wr.url or wr.req_id:
                hops.append(hop_from_memory(name="agent_memory.write", result=wr))
    if sc.write.write_assistant_summary and auto_writes < max_auto:
        wr = await write_memory_block(
            agent_memory,
            sc,
            final_answer,
            mode="agent",
            block_type=sc.write.default_type,
            summary=final_answer[:200] if final_answer else None,
            headers=write_headers,
            user_id=mem_user,
            zeus_session_id=sid,
            target=req.target,
            metrics=metrics,
            explicit=False,
            probe_available=probe_available,
        )
        if wr.ok:
            auto_writes += 1
            hops.append(hop_from_memory(name="agent_memory.write", result=wr))
            notes.append("semantic_cache.write: assistant_summary")
        elif not wr.skipped:
            notes.append(f"semantic_cache.write: fail={wr.error or wr.skip_reason}")

    finish_kw["layer_via"] = last_terminate_via
    finish_kw["tool_trail"] = tuple(trail)
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
        session=session_handle,
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
                "usage": dict(resp.usage or {}),
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
    chat_id: str = "",
    turn_id: str = "",
    force_trace: bool = False,
    rewind: bool = False,
    chat_session_id: str = "",
    brief_sha12: str = "",
    mini_sha12: str = "",
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
        if isinstance(tc_args, Mapping):
            tc_args = verb_body_without_rewind(tc_args)
        call_id = str(tc.get("id") or "").strip() or new_zeus_req_id()

        if isinstance(tc_args.get("summary"), str) and tc_args["summary"].strip():
            outcome.tool_arg_summary = tc_args["summary"].strip()

        if name in _TERMINATE_NAMES:
            final_summary = str(tc_args.get("summary") or "")
            return_seen = True
            outcome.return_args = dict(tc_args)
            outcome.terminate_via = "client_terminate"
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

        if name in (mw_ctx.data.get("denied_verbs") or []):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps({"error": "verb_denied", "verb": name}),
                }
            )
            outcome.steps.append(
                {"round": round_n, "type": "denied", "name": name, "args": tc_args}
            )
            continue

        if mw_ctx.data.get("hooks_must_refuse"):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps({"error": "turn_refused", "verb": name}),
                }
            )
            outcome.steps.append(
                {"round": round_n, "type": "refused", "name": name, "args": tc_args}
            )
            continue

        t_tool = time.perf_counter()
        hop = await zeus.call_verb(
            VerbRequest(
                verb=name,
                body=tc_args,
                target=target,
                mode_header=mode or "analytics",
                headers=correlation_headers(
                    chat_id=chat_id,
                    turn_id=turn_id,
                    call_id=call_id,
                    mode=mode or "analytics",
                    force_trace=force_trace,
                    trace_class=TRACE_CLASS_AGENT,
                    chat_session_id=chat_session_id,
                    brief_sha12=brief_sha12,
                    mini_sha12=mini_sha12,
                ),
                allow_pipeline=True,
                rewind=rewind,
            )
        )
        ms = int((time.perf_counter() - t_tool) * 1000)
        body = hop.body if isinstance(hop.body, Mapping) else {}
        text = json.dumps(body) if body else (hop.error or "")
        await middleware.after_zeus(mw_ctx, name, hop.status_code, body or text)
        override = mw_ctx.data.pop("tool_body_override", None)
        if isinstance(override, str) and override.strip():
            text = override
            try:
                parsed = json.loads(override)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = {"error": "untrusted_tool_payload"}
            body = parsed if isinstance(parsed, Mapping) else {"error": "untrusted_tool_payload"}
        shape = tool_payload_shape(body)
        get_family_logger().trace(
            "zeus_client.tool.result_shape",
            **{"verb": name, **shape, "redacted": True},
        )
        get_family_logger().trace(
            "zeus_client.tool.args_shape",
            **{
                "verb": name,
                "keys": [str(k) for k in list(tc_args.keys())[:24]]
                if isinstance(tc_args, Mapping)
                else [],
            },
        )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": text,
            }
        )
        meta = extract_pipeline_meta(body)
        hop_rec = {
            "req_id": hop.req_id,
            "name": name,
            "path_class": "pipeline" if name == "pipeline" else name,
            "status": hop.status_code,
            "ok": hop.ok,
            "ms": ms,
            "url": getattr(hop, "url", "") or "",
            "error": hop.error,
            "snippet": text[:TRACE_SNIPPET_MAX],
            "scope": f"{target.bucket}/{target.scope}" if target.bucket else "",
            **meta,
        }
        if isinstance(body, Mapping) and body:
            hop_rec["result_json"] = dict(body)
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
            if name not in _ORIENTATION_VERBS:
                outcome.tools_with_payload += 1

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
                outcome.terminate_via = "pipeline_turn_complete"

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
    chat_id: str = "",
    zeus_url: str | None = None,
    layer_via: str = "client_terminate",
    tool_trail: tuple[Mapping[str, Any], ...] = (),
    client_floor: str = "client-floor-5",
    base_id: str | None = None,
    hooks_score: float = 0.0,
    stamp: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
) -> TurnResult:
    from zeus_client._version import __version__ as PACKAGE_VERSION

    structured: StructuredResult | None = None
    layer_map: dict[str, Any] | None = None
    if layer is not None:
        layer_map = compact_layer_a(layer, via=layer_via)
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

    req_ids = collect_req_ids(hops)
    pref: str | None = None
    try:
        pref = select_primary_req_id(list(hops)) if hops else None
    except Exception:
        pref = None
    tokens = sum_provider_tokens(steps=steps)
    sid = session.session_id if session and session.session_id else None
    cst = session.contract_status if session else None
    chat = (session.chat_id if session and session.chat_id else None) or (chat_id or None)
    session_block: dict[str, Any] | None = None
    if sid or req_ids:
        session_block = {
            "id": sid,
            "req_ids": list(req_ids),
            "preferred_req_id": pref,
            "contract_status": cst,
        }

    inject_bag = inject_for_session_trace(
        system=system_prompt_of(messages=messages, catalog=chat_request),
        catalog=chat_request,
        rewind=bool((debug_policy or DebugPolicy()).rewind),
    )

    stamp_map = dict(stamp or {})
    if sid and "session_id" not in stamp_map:
        stamp_map = {**stamp_map, "session_id": sid}
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
        tokens=tokens,
        session=session_block,
        inject=inject_bag,
        stamp=stamp_map or None,
    )
    # G2 never in answer
    if "wish_i_knew" in answer:
        answer = (
            layer.summary if layer and layer.summary else answer.split("wish_i_knew")[0]
        ).strip()

    total_ms = int((time.time() - t0) * 1000)
    tgt = target
    target_map: dict[str, Any] = {}
    if tgt is not None:
        target_map = {
            "bucket": tgt.bucket,
            "scope": tgt.scope,
            "collection": tgt.collection,
            "mode": settings.mode,
        }
    system = ""
    for m in messages:
        if isinstance(m, Mapping) and m.get("role") == "system":
            c = m.get("content")
            if isinstance(c, str):
                system = c
                break
    flags = catalog_flags_of(
        system=system,
        catalog=dict(chat_request) if isinstance(chat_request, Mapping) else None,
    )
    catalog_block = {
        "has_scope_brief": flags["has_scope_brief"],
        "has_mini_schema": flags["has_mini_schema"],
        "tools_count": len(tools),
        "source": "tools" if tools else "none",
        "brief_sha12": flags.get("brief_sha12"),
        "mini_sha12": flags.get("mini_sha12"),
        "base_id": base_id,
        "client_floor": client_floor,
    }
    if not tools and isinstance(chat_request, Mapping) and chat_request.get("verbs"):
        catalog_block["source"] = "verbs"

    detective = None
    det_notes = list(notes)
    try:
        catalog = dict(chat_request) if isinstance(chat_request, Mapping) else None
        detective = safe_build_detective_briefing(
            enabled=(debug_policy or DebugPolicy()).detective_briefing,
            env=env,
            turn_id=turn_id,
            chat_id=chat or "",
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
            session_id=sid,
            target=target_map,
            contract_status=cst,
            ai_process_result=bool(settings.ai_process_result),
            ai_process_result_exit=ai_exit,
            public_trace=public,
            zeus_url=zeus_url,
            client_version=PACKAGE_VERSION,
            export_ref=turn_id,
        )
    except Exception as exc:  # noqa: BLE001
        det_notes.append(f"detective_briefing_failed: {exc}")
        detective = None

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
        chat_id=chat,
        session_id=sid,
        notes=tuple(det_notes),
        rounds=rounds,
        ai_process_result=bool(settings.ai_process_result),
        ai_process_result_exit=ai_exit,
        public_trace=public,
        hops=hops,
        journal_event_count=len(journal.events()),
        hooks_jailbreak_score=(
            float(decision.hooks_jailbreak_score) if decision is not None else float(hooks_score)
        ),
        detective=detective,
        preferred_req_id=pref_final
        if isinstance(pref_final, str) or pref_final is None
        else str(pref_final),
        req_ids=req_ids,
        zeus_url=zeus_url,
        client_version=PACKAGE_VERSION,
        target=target_map,
        catalog=catalog_block,
        contract_status=cst,
        tokens=tokens,
        export_ref=turn_id,
        journal_schema=1,
        stamp=stamp_map,
        trace_id=trace_id,
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
                "req_ids": list(req_ids),
                "trace_id": trace_id,
            },
        )
    except Exception:
        pass

    if error is not None:
        details = dict(error.details)
        details.setdefault("session.id", sid)
        if pref_final:
            details.setdefault("req_id", pref_final)
        if req_ids:
            details.setdefault("req_ids", list(req_ids))
        if zeus_url:
            details.setdefault("zeus.url", zeus_url)
        if target_map.get("scope"):
            details.setdefault(
                "scope",
                f"{target_map.get('bucket')}/{target_map.get('scope')}",
            )
        error = ErrorInfo(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            component=error.component,
            details=details,
        )

    log = get_family_logger()
    finish_attrs: dict[str, Any] = {
        "session.id": sid,
        "chat.id": chat,
        "turn.id": turn_id,
        "rounds": rounds,
        "duration_ms": total_ms,
        "zeus.url": zeus_url or "",
        "scope": (f"{target_map.get('bucket')}/{target_map.get('scope')}" if target_map else ""),
        "trace_id": trace_id,
        "mode": settings.mode,
    }
    if req_ids:
        finish_attrs["req_ids"] = list(req_ids)
        finish_attrs["req_id"] = pref_final or req_ids[-1]
    if error is None:
        result_tag = "forced_return" if status is TurnStatus.MAX_ROUNDS else "ok"
        log.info(
            "zeus_client.turn.finished",
            **{**finish_attrs, "result": result_tag},
        )
    else:
        log.error(
            "zeus_client.turn.failed",
            **{
                **finish_attrs,
                "result": "error",
                "error.type": error.code,
                "error.message": error.message,
            },
        )

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
        tool_trail=tool_trail,
    )
