"""Single-round LLM call and tool dispatch."""
from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from zeus_client.agent.enrichment import amplify_tool_content
from zeus_client.agent.hooks import AgentHooks
from zeus_client.agent.settings import effective_force_trace, effective_rewind
from zeus_client.constants import MAX_TOOLCALLS_PER_ROUND
from zeus_client.llm.client import cached_tokens_of, llm_chat_payload, llm_payload
from zeus_client.logging_setup import logger
from zeus_client.toon import to_toon
from zeus_client.trace.pipeline import pipeline_step_spans
from zeus_client.trace.session_hops import TRACE_SNIPPET_MAX, extract_pipeline_meta
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.dispatch import dispatch_zeus_call, zeus_correlation_headers

# Hub-aligned synthesis instructions (internal/admin/chat.go).
FORCED_FINAL_ANSWER_INSTRUCTION = (
    "The tool round budget is exhausted. Use only the tool results already "
    "present in this conversation to answer the user's latest question now. "
    "Do not call any tools. If the evidence is incomplete, say what is missing "
    "and give the best supported answer."
)

INSIGHT_AFTER_ZEUS_INSTRUCTION = (
    "Zeus tool results (including row/data payloads) are already in this "
    "conversation. Analyze that evidence and write a clear, useful answer for "
    "the operator: what was found, notable names/counts/patterns, and any "
    "caveats. Do not call tools. Do not re-run the same successful pipeline or "
    "invent rows/fields not present in the tool results. Prefer concrete "
    "details from the data over a one-line abstract summary."
)

# Kept for callers/tests that still want an explicit short synthesis prompt.
# Cheap ``ai_process_result=false`` no longer bills a second LLM hop by default
# (uses tool-arg summary or a static thin line instead).
CHEAP_FINAL_AFTER_ZEUS_INSTRUCTION = (
    "Zeus tool results are already in this conversation. Give a short final "
    "answer based only on that evidence. Do not call any tools. Prefer a brief "
    "summary over a long essay — the product UI will show the Zeus rows."
)

CHEAP_FINAL_STATIC_ANSWER = (
    "Zeus returned data. See structured results in the UI."
)


@dataclass
class ToolRoundOutcome:
    """What happened during one tool-dispatch round (for ai_process_result)."""

    return_seen: bool = False
    terminal_summary: Optional[str] = None
    # Last non-empty ``summary`` from tool-call args (pipeline often carries one).
    # Used by cheap ``ai_process_result=false`` so we can skip a second LLM hop.
    tool_arg_summary: Optional[str] = None
    tools_executed: int = 0
    tools_with_data: int = 0
    tools_empty: int = 0


def _is_empty_json_value(v: Any) -> bool:
    """Best-effort empty detection for Zeus tool payloads (Hub isEmptyJSONValue)."""
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, set)):
        return len(v) == 0
    if isinstance(v, dict):
        if not v:
            return True
        # Common Zeus envelopes
        for key in ("rows", "items", "results", "entities"):
            if key in v:
                return _is_empty_json_value(v.get(key))
        data = v.get("data")
        if data is not None:
            return _is_empty_json_value(data)
        result = v.get("result")
        if result is not None and result is not v:
            return _is_empty_json_value(result)
        # Non-empty dict without row lists — treat as data present
        return False
    return False


def _tool_result_empty(status: int, text: str, parsed: Any) -> bool:
    if status and status >= 400:
        return True
    if not (text or "").strip():
        return True
    if parsed is None:
        # Non-JSON body with content is non-empty
        return False
    return _is_empty_json_value(parsed)


def _has_turn_complete(parsed: Any, text: str) -> bool:
    """True when tool result body carries turn_complete:true (pipeline terminator)."""
    if isinstance(parsed, dict) and parsed.get("turn_complete") is True:
        return True
    if not text:
        return False
    try:
        m = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(m, dict) and m.get("turn_complete") is True


def _summary_from_terminal(parsed: Any, tc_args: dict) -> str:
    if isinstance(parsed, dict):
        for key in ("summary", "answer", "message"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return val
    if isinstance(tc_args, dict):
        val = tc_args.get("summary")
        if isinstance(val, str) and val.strip():
            return val
    return ""


async def run_llm_round(
    rnd, model, messages, tools, cache_body, cache_headers,
    base_url, api_key, hooks, ctx, trace, at_ms,
):
    """One AI chat-completion round. Returns (answer, should_break, msg_or_none)."""
    decision = await hooks.on_round_start(rnd, ctx)
    if decision:
        if decision.inject_messages:
            # RUN: splice extra messages (e.g. a user's loyalty profile) into
            # the conversation before the AI is called this round.
            messages.extend(decision.inject_messages)
            trace["notes"].append(
                f"hook injected {len(decision.inject_messages)} message(s) at round {rnd}"
            )
        if decision.stop:
            trace["notes"].append(f"stopped by hook: {decision.reason}")
            logger.info(f"run_agent: hook stopped round {rnd}: {decision.reason}")
            answer = decision.force_return if decision.force_return else None
            return answer, True, None

    await hooks.observe("round_start", {"round": rnd, "ctx": ctx})

    t_llm = time.time()
    llm_at = at_ms()
    payload = llm_payload(model, messages, tools, body_extra=cache_body)
    trace["ai_requests"].append({"round": rnd, "payload": deepcopy(payload)})
    status, resp = await llm_chat_payload(base_url, api_key, payload, extra_headers=cache_headers)
    llm_ms = int((time.time() - t_llm) * 1000)
    cached_tok = cached_tokens_of(resp)
    trace["spans"].append({"name": f"ai.chat.round.{rnd}", "cls": "ai", "at": llm_at, "ms": llm_ms})
    trace["ai_responses"].append({
        "round": rnd, "status": status, "ms": llm_ms,
        "cached_tokens": cached_tok, "body": deepcopy(resp),
    })

    await hooks.observe("ai_response", {"round": rnd, "response": resp, "ctx": ctx})

    decision = await hooks.on_ai_response(resp, ctx)
    if decision and decision.stop:
        trace["notes"].append(f"stopped after AI by hook: {decision.reason}")
        answer = decision.force_return if decision.force_return else None
        return answer, True, None

    if status != 200 or not isinstance(resp, dict):
        snippet = resp if isinstance(resp, str) else json.dumps(resp)
        answer = f"⚠️ Upstream LLM error (HTTP {status}): {snippet[:600]}"
        trace["steps"].append({"round": rnd, "type": "llm_error", "ms": llm_ms, "detail": snippet[:600]})
        return answer, True, None

    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    tool_calls = msg.get("tool_calls") or []
    trace["steps"].append({
        "round": rnd, "type": "llm", "ms": llm_ms,
        "finish_reason": choice.get("finish_reason"),
        "tool_calls": [tc.get("function", {}).get("name") for tc in tool_calls],
        "usage": resp.get("usage", {}),
    })

    if not tool_calls:
        answer = msg.get("content") or "(model returned no content)"
        messages.append({"role": "assistant", "content": answer})
        return answer, True, None

    return None, False, msg


async def force_final_llm_answer(
    rnd,
    model,
    messages,
    cache_body,
    cache_headers,
    base_url,
    api_key,
    hooks,
    ctx,
    trace,
    at_ms,
    *,
    instruction: str = "",
    cause: str = "force_final",
):
    """One no-tools synthesis pass after Zeus tool results are already spliced.

    Mirrors Hub forceFinalChatAnswer. Empty ``instruction`` uses the round-budget
    forced-final text. Returns the assistant content string (may be empty).
    """
    text = (instruction or "").strip() or FORCED_FINAL_ANSWER_INSTRUCTION
    messages.append({"role": "user", "content": text})
    trace["notes"].append(f"force_final: {cause}")

    t_llm = time.time()
    llm_at = at_ms()
    # No tools — OpenAI-compatible providers reject tool_choice without tools.
    payload = llm_payload(model, messages, tools=None, body_extra=cache_body)
    trace["ai_requests"].append({
        "round": rnd, "payload": deepcopy(payload), "force_final": cause,
    })
    status, resp = await llm_chat_payload(
        base_url, api_key, payload, extra_headers=cache_headers,
    )
    llm_ms = int((time.time() - t_llm) * 1000)
    cached_tok = cached_tokens_of(resp)
    trace["spans"].append({
        "name": f"ai.chat.force_final.{rnd}", "cls": "ai", "at": llm_at, "ms": llm_ms,
        "cause": cause,
    })
    trace["ai_responses"].append({
        "round": rnd, "status": status, "ms": llm_ms,
        "cached_tokens": cached_tok, "body": deepcopy(resp),
        "force_final": cause,
    })

    await hooks.observe("ai_response", {
        "round": rnd, "response": resp, "ctx": ctx, "force_final": cause,
    })

    if status != 200 or not isinstance(resp, dict):
        snippet = resp if isinstance(resp, str) else json.dumps(resp)
        trace["notes"].append(f"force_final_failed: HTTP {status} {snippet[:200]}")
        return ""

    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    # Ignore tool_calls on forced final — we asked for prose only.
    content = (msg.get("content") or "").strip()
    if content:
        messages.append({"role": "assistant", "content": content})
        usage = resp.get("usage", {}) if isinstance(resp.get("usage"), dict) else {}
        trace["steps"].append({
            "round": rnd, "type": "force_final", "ms": llm_ms,
            "cause": cause, "content_len": len(content),
            "finish_reason": choice.get("finish_reason"),
            "usage": usage,
        })
        return content
    trace["notes"].append(f"force_final_empty: {cause}")
    return ""


async def execute_tool_calls(
    rnd, tool_calls, messages, api_version, zeus_url, bucket, scope, collection,
    zcfg, zeus_headers, hooks, ctx, trace, at_ms, turn_id, conv_id,
    toon_on, this_turn_reqs,
):
    """Dispatch tool calls for one round.

    Returns ``(answer, should_break, zeus_headers, outcome)``.
    ``should_break`` is True when a terminating ``return`` / pipeline was seen
    (loop still decides cheap vs insight via ``ai_process_result``).
    """
    answer = None
    final_summary = None
    return_seen = False
    outcome = ToolRoundOutcome()

    mode = ""
    if isinstance(ctx, dict):
        mode = str(ctx.get("mode") or "")
    force_trace = effective_force_trace(
        ctx.get("settings") if isinstance(ctx, dict) else None,
        zcfg if isinstance(zcfg, dict) else None,
    )
    rewind = effective_rewind(
        ctx.get("settings") if isinstance(ctx, dict) else None,
        zcfg if isinstance(zcfg, dict) else None,
    )

    for tc in tool_calls[:MAX_TOOLCALLS_PER_ROUND]:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        try:
            tc_args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            tc_args = {}

        if isinstance(tc_args, dict):
            arg_sum = tc_args.get("summary")
            if isinstance(arg_sum, str) and arg_sum.strip():
                outcome.tool_arg_summary = arg_sum.strip()

        if name in ("return_result", "return"):
            final_summary = tc_args.get("summary", "") or ""
            return_seen = True
            messages.append({
                "role": "tool", "tool_call_id": tc.get("id"),
                "name": name, "content": json.dumps(tc_args),
            })
            trace["steps"].append({"round": rnd, "type": name, "args": tc_args})
            continue

        await hooks.observe("tool_call_planned", {
            "round": rnd, "name": name, "args": tc_args, "ctx": ctx,
        })
        tc_args = await hooks.before_zeus_dispatch(name, tc_args, ctx)
        if isinstance(tc_args, dict):
            arg_sum = tc_args.get("summary")
            if isinstance(arg_sum, str) and arg_sum.strip():
                outcome.tool_arg_summary = arg_sum.strip()

        t0 = time.time()
        tool_at = at_ms()
        corr = zeus_correlation_headers(
            conv_id or "",
            turn_id=turn_id,
            call_id=tc.get("id") or f"call_{rnd}_{len(trace.get('tool_calls', []))}",
            mode=mode,
            force_trace=force_trace,
        )
        sent_corr = {k: v for k, v in corr.items() if k.startswith("X-Zeus")}
        tstatus, ttext, dispatch_url, req_id = await dispatch_zeus_call(
            api_version, zeus_url, bucket, scope, collection, name, tc_args,
            zeus_headers, corr_headers=corr, rewind=rewind)

        if tstatus == 401 and zcfg.get("auth_mode") == "basic":
            logger.warning("run_agent: 401 on dispatch with basic auth -> forcing re-mint and retry")
            try:
                zeus_headers, auth_note = await resolve_zeus_auth(
                    zeus_url, zcfg, bucket, scope, force=True)
                # Preserve mode / force-trace after re-mint.
                if mode and "X-Zeus-Mode" not in zeus_headers:
                    zeus_headers = {**zeus_headers, "X-Zeus-Mode": mode}
                if force_trace:
                    zeus_headers = {**zeus_headers, "X-Zeus-Trace": "1"}
                trace["notes"].append(f"auth: re-minted after 401 ({auth_note})")
                tstatus, ttext, dispatch_url, req_id = await dispatch_zeus_call(
                    api_version, zeus_url, bucket, scope, collection, name, tc_args,
                    zeus_headers, corr_headers=corr, rewind=rewind)
            except (RuntimeError, httpx.HTTPError) as e:
                trace["notes"].append(f"auth: re-mint after 401 failed ({e})")

        ttext = await hooks.after_zeus_dispatch(name, tc_args, tstatus, ttext, ctx)

        tool_ms = int((time.time() - t0) * 1000)
        try:
            parsed_result = json.loads(ttext)
        except (TypeError, ValueError):
            parsed_result = None
        if name == "pipeline":
            trace["spans"].extend(pipeline_step_spans(tool_at, tool_ms, tc_args, parsed_result))
        else:
            trace["spans"].append({"name": f"tool.{name}", "cls": "tool", "at": tool_at, "ms": tool_ms})

        ai_content = to_toon(ttext) if toon_on else ttext
        ai_content = amplify_tool_content(name, tstatus, ttext, ai_content)

        messages.append({
            "role": "tool", "tool_call_id": tc.get("id"),
            "name": name, "content": ai_content,
        })
        tool_record = {
            "round": rnd, "name": name, "args": deepcopy(tc_args),
            "status": tstatus, "ms": tool_ms, "url": dispatch_url,
            "req_id": req_id, "x_zeus_headers": sent_corr,
            "bytes": len(ttext.encode("utf-8")),
            "sent_bytes": len(ai_content.encode("utf-8")),
            "result_text": ttext, "result_json": parsed_result,
            "ai_content": ai_content,
            "ai_content_format": "toon" if toon_on else "json_or_text",
        }
        trace["tool_calls"].append(tool_record)
        await hooks.observe("zeus_result", {
            "round": rnd, "name": name, "args": tc_args,
            "status": tstatus, "result_text": ttext,
            "result_json": parsed_result, "ctx": ctx,
        })
        pipe_meta = extract_pipeline_meta(parsed_result) if parsed_result is not None else {}
        if name == "pipeline" and isinstance(parsed_result, dict):
            step_costs = (parsed_result.get("meta") or {}).get("step_costs")
            if step_costs is None and isinstance(parsed_result.get("data"), dict):
                step_costs = (parsed_result["data"].get("meta") or {}).get("step_costs")
        else:
            step_costs = pipe_meta.get("step_costs")
        trace["steps"].append({
            "round": rnd, "type": "tool", "name": name, "args": tc_args,
            "status": tstatus, "ms": tool_ms, "url": dispatch_url,
            "req_id": req_id, "x_zeus_headers": sent_corr,
            "bytes": len(ttext.encode("utf-8")),
            "sent_bytes": len(ai_content.encode("utf-8")),
            "result": ttext[:4000], "result_full": ttext,
            "pipeline_json": tc_args if name == "pipeline" else None,
            "pipeline_step_costs": step_costs if name == "pipeline" else None,
        })
        if req_id:
            snip = (ttext or "")[:TRACE_SNIPPET_MAX]
            hop = {
                "req_id": req_id,
                "name": name,
                "status": tstatus,
                "snippet": snip,
                "url": dispatch_url,
                "ms": tool_ms,
                "bytes": len(ttext.encode("utf-8")),
            }
            hop.update({k: v for k, v in pipe_meta.items() if k != "ms_meta"})
            if step_costs is not None:
                hop["step_costs"] = step_costs
            this_turn_reqs.append(hop)

        outcome.tools_executed += 1
        empty = _tool_result_empty(tstatus, ttext or "", parsed_result)
        if empty:
            outcome.tools_empty += 1
        else:
            outcome.tools_with_data += 1

        # Terminating pipeline (turn_complete) — Hub returnResultSeen path
        if name == "pipeline" and _has_turn_complete(parsed_result, ttext or ""):
            return_seen = True
            if not final_summary:
                final_summary = _summary_from_terminal(parsed_result, tc_args)

    outcome.return_seen = return_seen
    outcome.terminal_summary = final_summary if return_seen else None

    if return_seen:
        # Do not append assistant yet — loop may run an insight synthesis turn
        # (ai_process_result=true) or take the cheap terminal summary (false).
        answer = final_summary if final_summary is not None else ""
        return answer, True, zeus_headers, outcome

    return None, False, zeus_headers, outcome
