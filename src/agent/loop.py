"""Agent loop orchestrator — one user-question turn."""
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from zeus_client.contract_hash import compute_contract_hash, extract_stamped_hash

from zeus_client.agent.audit import run_runtime_contract_audit
from zeus_client.agent.hooks import AgentHooks
from zeus_client.agent.response import extract_structured_response
from zeus_client.agent.session_phase import commit_session_turn, setup_contract_and_session
from zeus_client.agent.tool_round import execute_tool_calls, run_llm_round
from zeus_client.constants import MAX_ROUNDS, normalize_api_version
from zeus_client.llm.client import cache_hints
from zeus_client.logging_setup import logger
from zeus_client.toon import _toon_encode
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.catalog import (
    apply_injected_business_logic,
    load_chat_request,
    tools_from_chat_request,
)
from zeus_client.zeus.lint import lint_catalog_assembled, resolve_lint_config


@dataclass
class TurnContext:
    """Fields threaded through one agent turn."""
    trace: dict
    messages: list
    zeus_headers: dict
    chat_req: dict
    system_msg: dict
    tools: list
    ctx: dict
    turn_id: str = ""
    sid: str = ""
    this_user_round: int = 1
    contract_id: str = ""
    contract_hash: str = ""
    bound_contract_hash: str = ""
    enable_sessions: bool = True
    stamped_h: str = ""
    current_content_h: str = ""
    this_turn_reqs: list = field(default_factory=list)
    toon_on: bool = False
    cache_headers: dict = field(default_factory=dict)
    cache_body: dict = field(default_factory=dict)


async def setup_turn_context(
    zeus_url, zcfg, api_version, mode, bucket, scope,
    user_msg, prior_turns, optimized, provider_id, base_url, conv_id,
) -> TurnContext:
    """Initialize trace, auth, catalog load, and contract prep."""
    api_version = normalize_api_version(api_version)
    trace = {
        "steps": [], "rounds": 0, "notes": [], "total_ms": 0, "spans": [],
        "ai_requests": [], "ai_responses": [], "tool_calls": [],
    }
    t_turn = time.time()

    def at_ms():
        return int((time.time() - t_turn) * 1000)

    t0 = time.time()
    zeus_headers, auth_note = await resolve_zeus_auth(zeus_url, zcfg, bucket, scope)
    trace["notes"].append(f"auth: {auth_note}")
    trace["spans"].append({
        "name": "auth.resolve", "cls": "other",
        "at": 0, "ms": int((time.time() - t0) * 1000),
    })

    t0 = time.time()
    chat_req, src_note = await load_chat_request(
        zeus_url, api_version, mode, bucket, scope, zeus_headers)
    trace["notes"].append(f"chat_request: {src_note}")
    trace["spans"].append({
        "name": "chat_request.load", "cls": "other",
        "at": int((t0 - t_turn) * 1000),
        "ms": int((time.time() - t0) * 1000),
    })

    # Render any operator-injected business rules (guidance.injections.
    # business_logic) into the system prompt so they reach the LLM. Spliced
    # after the scope brief, so it is stripped before hashing and does not
    # affect contract binding. No-op when there are no rules.
    _bl = (
        ((chat_req.get("guidance") or {}).get("injections") or {})
        .get("business_logic") or []
    )
    if _bl:
        chat_req = apply_injected_business_logic(chat_req)
        trace["notes"].append(f"business_logic: {len(_bl)} injected rule(s) merged")

    # Assemble-time catalog lint (ZC-35 soft + ZC-36 hard / open-vs-locked).
    # Cached by (contract_hash, open_rules_hash); not re-run every tool round.
    # Never blocks the turn and never rewrites locked content.
    # Enable via guidance.debug, guidance.catalog_lint.mode, or ZEUS_CATALOG_LINT_MODE.
    try:
        lint_cfg = resolve_lint_config(chat_req)
        if lint_cfg.should_run_in_agent():
            lint_report = lint_catalog_assembled(chat_req, config=lint_cfg)
            if lint_cfg.attach_full_report_to_trace() or lint_report.hard_finding_count or lint_report.open_vs_locked_count:
                trace["catalog_lint"] = lint_report.to_dict()
            trace["notes"].append(lint_report.summary_line())
    except Exception as exc:
        trace["notes"].append(f"catalog_lint_failed: {exc}")

    stamped_h = ""
    current_content_h = ""
    try:
        stamped_h = extract_stamped_hash(chat_req)
        current_content_h = compute_contract_hash(chat_req)
    except Exception:
        pass

    system_msg = chat_req["messages"][0]
    tools = tools_from_chat_request(chat_req)
    system_content = system_msg.get("content") or ""
    trace["api_version"] = api_version
    trace["catalog"] = {
        "source": src_note,
        "has_scope_brief": "## SCOPE BRIEF" in system_content,
        "has_mini_schema": "## MINI-SCHEMA" in system_content,
        "system_message": system_msg,
        "tools": tools,
        "tool_names": [(t.get("function") or t).get("name") for t in tools],
    }
    trace["notes"].append(f"api version: {api_version.upper()}")
    trace["notes"].append(f"tools available: {len(tools)}")
    if chat_req.get("_format") or chat_req.get("verbs"):
        trace["notes"].append(
            "catalog shape: new standardized (prototype-style with instructions/verbs/guidance)"
        )
    toon_on = bool(optimized) and _toon_encode is not None
    trace["notes"].append(
        "optimized: tool results sent to AI as TOON" if toon_on
        else "optimized: off (tool results sent as JSON)"
    )

    ctx = {
        "user_msg": user_msg, "bucket": bucket, "scope": scope,
        "collection": None, "mode": mode, "api_version": api_version,
        "_t_turn": t_turn, "_at_ms": at_ms,
    }
    cache_headers, cache_body = cache_hints(provider_id, base_url, conv_id)
    if cache_headers or cache_body:
        keys = list(cache_headers) + list(cache_body)
        trace["notes"].append(f"prompt cache: {provider_id} hints sent ({', '.join(keys)})")
    else:
        trace["notes"].append(f"prompt cache: {provider_id} caches automatically on prefix match")

    messages = [system_msg] + list(prior_turns) + [{"role": "user", "content": user_msg}]

    return TurnContext(
        trace=trace,
        messages=messages,
        zeus_headers=zeus_headers,
        chat_req=chat_req,
        system_msg=system_msg,
        tools=tools,
        ctx=ctx,
        stamped_h=stamped_h,
        current_content_h=current_content_h,
        toon_on=toon_on,
        cache_headers=cache_headers,
        cache_body=cache_body,
    )


async def run_agent(
    zeus_url, zcfg, base_url, api_key, model, api_version, mode,
    bucket, scope, collection, user_msg, prior_turns,
    optimized=True, provider_id=None, conv_id=None,
    zeus_session_id: str = "", zeus_round: int = 0,
    hooks: Optional[AgentHooks] = None,
    structured: bool = False,
    output_schema=None,
):
    """Run one user-question turn (LLM + Zeus dispatches).

    When ``structured=True``, returns a 5-tuple with a
    :class:`~zeus_client.agent.response.StructuredAgentResponse` as the last
    element (schema-filtered ``zeus_data`` rows plus decomposition metadata).
    """
    api_version = normalize_api_version(api_version)
    logger.debug(
        f"run_agent: START conv_id={conv_id} mode={mode} api={api_version} "
        f"sample_scope={bucket}/{scope}"
    )

    tc = await setup_turn_context(
        zeus_url, zcfg, api_version, mode, bucket, scope,
        user_msg, prior_turns, optimized, provider_id, base_url, conv_id,
    )
    tc.ctx["collection"] = collection

    sess = await setup_contract_and_session(
        zeus_url, zcfg, bucket, scope, mode, tc.chat_req, user_msg,
        zeus_session_id, zeus_round, tc.trace, tc.current_content_h, tc.stamped_h,
        tc.zeus_headers,
    )
    tc.sid = sess["sid"]
    tc.turn_id = sess["turn_id"]
    tc.this_user_round = sess["this_user_round"]
    tc.contract_id = sess["contract_id"]
    tc.contract_hash = sess["contract_hash"]
    tc.bound_contract_hash = sess.get("bound_contract_hash") or tc.contract_hash
    tc.enable_sessions = sess["enable_sessions"]
    tc.stamped_h = sess.get("stamped_h") or tc.stamped_h
    tc.current_content_h = sess.get("current_content_h") or tc.current_content_h

    hooks = hooks or AgentHooks()
    await hooks.observe("run_start", {"ctx": tc.ctx, "has_prior_turns": bool(prior_turns)})
    await hooks.observe("contract_status", {
        "contract_id": tc.contract_id,
        "status": (tc.trace.get("session") or {}).get("contract_status") or "none",
        "ctx": tc.ctx,
    })

    at_ms = tc.ctx["_at_ms"]
    answer = None

    for rnd in range(1, MAX_ROUNDS + 1):
        tc.trace["rounds"] = rnd

        answer, should_break, msg = await run_llm_round(
            rnd, model, tc.messages, tc.tools, tc.cache_body, tc.cache_headers,
            base_url, api_key, hooks, tc.ctx, tc.trace, at_ms,
        )
        if should_break:
            break

        tc.messages.append(msg)

        answer, should_break, tc.zeus_headers = await execute_tool_calls(
            rnd, msg.get("tool_calls") or [], tc.messages,
            api_version, zeus_url, bucket, scope, collection,
            zcfg, tc.zeus_headers, hooks, tc.ctx, tc.trace, at_ms,
            tc.turn_id, conv_id, tc.toon_on, tc.this_turn_reqs,
        )
        await hooks.observe("round_end", {
            "round": rnd, "answer_ready": should_break, "ctx": tc.ctx,
        })
        if should_break:
            break
        if not await hooks.should_continue(rnd, tc.messages, tc.ctx):
            tc.trace["notes"].append(f"stopped by should_continue hook at round {rnd}")
            answer = "(stopped early by should_continue hook)"
            break
    else:
        answer = "⚠️ Ran out of tool rounds before the model produced a final answer."

    await hooks.observe("final_answer", {"answer": answer, "ctx": tc.ctx})

    produced_delta = (
        tc.messages[1:][len(prior_turns):] if prior_turns is not None else tc.messages[1:]
    )
    session_meta = await commit_session_turn(
        zeus_url, tc.sid, tc.enable_sessions, tc.this_user_round,
        tc.contract_id, tc.contract_hash, tc.chat_req, produced_delta,
        prior_turns, tc.this_turn_reqs, tc.trace, tc.zeus_headers,
    )

    t_turn = tc.ctx["_t_turn"]
    tc.trace["total_ms"] = int((time.time() - t_turn) * 1000)
    tc.trace["final_messages"] = deepcopy(tc.messages[1:])
    logger.info(
        f"run_agent: DONE answer_len={len(answer or '')} total_ms={tc.trace['total_ms']}"
    )

    run_runtime_contract_audit(
        tc.trace, user_msg, tc.stamped_h, tc.current_content_h,
        tc.bound_contract_hash, tc.contract_id,
    )

    if structured:
        structured_response = extract_structured_response(
            answer, tc.trace, tc.chat_req, output_schema=output_schema,
        )
        for w in structured_response.warnings:
            tc.trace["notes"].append(f"[WARN] {w}")
        tc.trace["structured_response"] = {
            "zeus_data_count": len(structured_response.zeus_data),
            "entity_type": structured_response.entity_type,
            "source_tool": structured_response.source_tool,
        }
        return answer, tc.trace, tc.messages[1:], session_meta, structured_response

    return answer, tc.trace, tc.messages[1:], session_meta