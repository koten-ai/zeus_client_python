"""Single-round LLM call and tool dispatch."""
import json
import time
from copy import deepcopy

import httpx

from zeus_client.agent.enrichment import amplify_tool_content
from zeus_client.agent.hooks import AgentHooks
from zeus_client.constants import MAX_TOOLCALLS_PER_ROUND
from zeus_client.llm.client import cached_tokens_of, llm_chat_payload, llm_payload
from zeus_client.logging_setup import logger
from zeus_client.toon import to_toon
from zeus_client.trace.pipeline import pipeline_step_spans
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.dispatch import dispatch_zeus_call, zeus_correlation_headers


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


async def execute_tool_calls(
    rnd, tool_calls, messages, api_version, zeus_url, bucket, scope, collection,
    zcfg, zeus_headers, hooks, ctx, trace, at_ms, turn_id, conv_id,
    toon_on, this_turn_reqs,
):
    """Dispatch tool calls for one round. Returns (answer, should_break)."""
    answer = None
    final_summary = None

    for tc in tool_calls[:MAX_TOOLCALLS_PER_ROUND]:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        try:
            tc_args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            tc_args = {}

        if name in ("return_result", "return"):
            final_summary = tc_args.get("summary", "")
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

        t0 = time.time()
        tool_at = at_ms()
        corr = zeus_correlation_headers(
            conv_id or "", turn_id=turn_id,
            call_id=tc.get("id") or f"call_{rnd}_{len(trace.get('tool_calls', []))}",
        )
        sent_corr = {k: v for k, v in corr.items() if k.startswith("X-Zeus")}
        tstatus, ttext, dispatch_url, req_id = await dispatch_zeus_call(
            api_version, zeus_url, bucket, scope, collection, name, tc_args,
            zeus_headers, corr_headers=corr)

        if tstatus == 401 and zcfg.get("auth_mode") == "basic":
            logger.warning("run_agent: 401 on dispatch with basic auth -> forcing re-mint and retry")
            try:
                zeus_headers, auth_note = await resolve_zeus_auth(
                    zeus_url, zcfg, bucket, scope, force=True)
                trace["notes"].append(f"auth: re-minted after 401 ({auth_note})")
                tstatus, ttext, dispatch_url, req_id = await dispatch_zeus_call(
                    api_version, zeus_url, bucket, scope, collection, name, tc_args,
                    zeus_headers, corr_headers=corr)
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
        trace["steps"].append({
            "round": rnd, "type": "tool", "name": name, "args": tc_args,
            "status": tstatus, "ms": tool_ms, "url": dispatch_url,
            "req_id": req_id, "x_zeus_headers": sent_corr,
            "bytes": len(ttext.encode("utf-8")),
            "sent_bytes": len(ai_content.encode("utf-8")),
            "result": ttext[:4000], "result_full": ttext,
            "pipeline_json": tc_args if name == "pipeline" else None,
            "pipeline_step_costs": (
                (parsed_result.get("meta") or {}).get("step_costs")
                if name == "pipeline" and isinstance(parsed_result, dict) else None
            ),
        })
        if req_id:
            this_turn_reqs.append((req_id, name, tstatus, (ttext or "")[:300], dispatch_url))

    if final_summary is not None:
        answer = final_summary
        messages.append({"role": "assistant", "content": answer})
        return answer, True, zeus_headers

    return None, False, zeus_headers