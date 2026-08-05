"""Agent loop orchestrator — one user-question turn."""
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Union

from zeus_client.contract_hash import compute_contract_hash, extract_stamped_hash

from zeus_client.agent.audit import run_runtime_contract_audit
from zeus_client.agent.hooks import AgentHooks
from zeus_client.agent.layer_a import user_facing_answer
from zeus_client.agent.prompt_inject import apply_control_plane_inject
from zeus_client.agent.response import extract_structured_response
from zeus_client.agent.session_phase import commit_session_turn, setup_contract_and_session
from zeus_client.agent.settings import (
    ClientSettings,
    effective_ai_process_result,
    effective_force_trace,
    prepare_settings,
)
from zeus_client.agent.tool_round import (
    CHEAP_FINAL_STATIC_ANSWER,
    INSIGHT_AFTER_ZEUS_INSTRUCTION,
    execute_tool_calls,
    force_final_llm_answer,
    run_llm_round,
)
from zeus_client.constants import MAX_ROUNDS, normalize_api_version
from zeus_client.llm.client import cache_hints
from zeus_client.logging_setup import logger
from zeus_client.toon import _toon_encode
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.base_catalog import load_base_catalog
from zeus_client.zeus.catalog import (
    apply_injected_business_logic,
    load_chat_request,
    tools_from_chat_request,
)
from zeus_client.zeus.dispatch import apply_zeus_force_trace_header, apply_zeus_mode_header
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
    settings: Optional[ClientSettings] = None
    max_rounds: int = MAX_ROUNDS


async def setup_turn_context(
    zeus_url, zcfg, api_version, mode, bucket, scope,
    user_msg, prior_turns, optimized, provider_id, base_url, conv_id,
    *,
    base_id: Optional[str] = None,
    base_catalog_dirs: Optional[list] = None,
    settings: Optional[Union[ClientSettings, Mapping[str, Any]]] = None,
    chat_req_override: Optional[dict] = None,
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

    prepared: Optional[ClientSettings] = None
    if settings is not None:
        prepared = prepare_settings(settings)
        trace["notes"].append(
            f"settings: ruleset_id={prepared.ruleset_id} "
            f"rules={len(prepared.rules or {})}"
        )
        if prepared.deployment_id:
            trace["notes"].append(f"deployment_id={prepared.deployment_id}")
        if prepared.locale or prepared.channel or prepared.timezone:
            trace["notes"].append(
                "session_meta: "
                + ",".join(
                    f"{k}={v}"
                    for k, v in (
                        ("locale", prepared.locale),
                        ("channel", prepared.channel),
                        ("tz", prepared.timezone),
                        ("lang", prepared.language),
                    )
                    if v
                )
            )

    t0 = time.time()
    zeus_headers, auth_note = await resolve_zeus_auth(zeus_url, zcfg, bucket, scope)
    # Stamp mode on every agent request so TraceBundle envelope can pick it up
    # (pipeline path still under-instrumented server-side; header is still useful
    # for standalone verbs and logs).
    zeus_headers = apply_zeus_mode_header(zeus_headers, mode)
    zeus_headers = apply_zeus_force_trace_header(
        zeus_headers, effective_force_trace(prepared, zcfg),
    )
    trace["notes"].append(f"auth: {auth_note}")
    if mode:
        trace["notes"].append(f"X-Zeus-Mode={mode}")
    if zeus_headers.get("X-Zeus-Trace") == "1":
        trace["notes"].append("X-Zeus-Trace=1 (force keep)")
    trace["spans"].append({
        "name": "auth.resolve", "cls": "other",
        "at": 0, "ms": int((time.time() - t0) * 1000),
    })

    t0 = time.time()
    if chat_req_override is not None:
        chat_req = deepcopy(chat_req_override)
        src_note = "override"
    elif base_id:
        dirs = list(base_catalog_dirs or [])
        if not dirs:
            from zeus_client.constants import chat_request_search_dirs, bundled_chat_requests_dir
            dirs = list(chat_request_search_dirs(bucket, scope) or [])
            dirs.append(bundled_chat_requests_dir())
        chat_req = load_base_catalog(
            base_id=base_id, mode=mode or "analytics", search_dirs=dirs,
        )
        src_note = f"base_id={base_id}"
        # Optional live brief merge when Zeus reachable and no brief present
        try:
            from zeus_client.zeus.catalog import extract_scope_brief, load_live_chat_request, merge_scope_brief
            if not extract_scope_brief(chat_req):
                live = await load_live_chat_request(
                    zeus_url, mode, bucket, scope, zeus_headers,
                )
                brief = extract_scope_brief(live) if live else ""
                if brief:
                    chat_req = merge_scope_brief(chat_req, brief)
                    src_note += " + live scope brief"
        except Exception as exc:
            src_note += f"; live brief skipped: {exc}"
    else:
        chat_req, src_note = await load_chat_request(
            zeus_url, api_version, mode, bucket, scope, zeus_headers)
    trace["notes"].append(f"chat_request: {src_note}")
    if base_id:
        lineage = (chat_req.get("_lineage") or {}) if isinstance(chat_req, dict) else {}
        trace["catalog_base_id"] = lineage.get("base_id") or base_id
    trace["spans"].append({
        "name": "chat_request.load", "cls": "other",
        "at": int((t0 - t_turn) * 1000),
        "ms": int((time.time() - t0) * 1000),
    })

    # base-5 control-plane inject (hash-excluded zones after SCOPE BRIEF)
    if prepared is not None:
        chat_req = apply_control_plane_inject(chat_req, prepared)
        trace["notes"].append("control_plane: rules/company/output_request inject applied")
        trace["ruleset_id"] = prepared.ruleset_id
        trace["control_plane"] = {
            "ruleset_id": prepared.ruleset_id,
            "rule_ids": sorted((prepared.rules or {}).keys()),
            "has_company_context": bool(prepared.company_context),
            "has_output_request": bool(prepared.output_request),
            "locale": prepared.locale,
            "channel": prepared.channel,
            "timezone": prepared.timezone,
            "deployment_id": prepared.deployment_id,
        }

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

    max_rounds = MAX_ROUNDS
    if prepared and prepared.max_rounds:
        max_rounds = max(1, int(prepared.max_rounds))
    ai_process = effective_ai_process_result(prepared)
    # Insight after Zeus tools needs at least 2 AI hops when the first hop
    # only plans tools (Hub / ROADMAP open question: floor max_rounds).
    if ai_process and max_rounds < 2:
        max_rounds = 2
        trace["notes"].append(
            "ai_process_result=true: max_rounds raised to 2 for insight turn"
        )
    trace["notes"].append(f"ai_process_result={str(ai_process).lower()}")

    ctx = {
        "user_msg": user_msg, "bucket": bucket, "scope": scope,
        "collection": None, "mode": mode, "api_version": api_version,
        "_t_turn": t_turn, "_at_ms": at_ms,
        "base_id": base_id,
        "ruleset_id": prepared.ruleset_id if prepared else None,
        "settings": prepared,
        "ai_process_result": ai_process,
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
        settings=prepared,
        max_rounds=max_rounds,
    )


def _ai_process_from_tc(tc: TurnContext) -> bool:
    if tc.ctx and "ai_process_result" in tc.ctx:
        return bool(tc.ctx["ai_process_result"])
    return effective_ai_process_result(tc.settings)


async def run_agent(
    zeus_url, zcfg, base_url, api_key, model, api_version, mode,
    bucket, scope, collection, user_msg, prior_turns,
    optimized=True, provider_id=None, conv_id=None,
    zeus_session_id: str = "", zeus_round: int = 0,
    hooks: Optional[AgentHooks] = None,
    structured: bool = False,
    output_schema=None,
    base_id: Optional[str] = None,
    base_catalog_dirs: Optional[list] = None,
    settings: Optional[Union[ClientSettings, Mapping[str, Any]]] = None,
    chat_req_override: Optional[dict] = None,
):
    """Run one user-question turn (LLM + Zeus dispatches).

    When ``structured=True``, returns a 5-tuple with a
    :class:`~zeus_client.agent.response.StructuredAgentResponse` as the last
    element (schema-filtered ``zeus_data`` rows plus decomposition metadata).

    base-5 control plane:
      - ``base_id``: load ``chat_request_<mode>_<base_id>.json`` (ZC-WISH-001)
      - ``settings``: rules merge/freeze, company_context, output_request, locale…
      - post-terminate policy table when structured or settings present
      - ``settings.ai_process_result`` (default True): after Zeus tool data,
        True = insight synthesis turn; False = cheap terminal / thin final
    """
    api_version = normalize_api_version(api_version)
    logger.debug(
        f"run_agent: START conv_id={conv_id} mode={mode} api={api_version} "
        f"sample_scope={bucket}/{scope} base_id={base_id or '-'}"
    )

    tc = await setup_turn_context(
        zeus_url, zcfg, api_version, mode, bucket, scope,
        user_msg, prior_turns, optimized, provider_id, base_url, conv_id,
        base_id=base_id,
        base_catalog_dirs=base_catalog_dirs,
        settings=settings,
        chat_req_override=chat_req_override,
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
    max_rounds = tc.max_rounds
    ai_process = _ai_process_from_tc(tc)

    for rnd in range(1, max_rounds + 1):
        tc.trace["rounds"] = rnd

        # ZC-WISH-021: force final return when budget nearly exhausted
        force_left = None
        if tc.settings and tc.settings.force_return_rounds_left is not None:
            force_left = int(tc.settings.force_return_rounds_left)
        remaining = max_rounds - rnd
        if force_left is not None and remaining <= force_left and rnd > 1:
            tc.trace["notes"].append(
                f"force_return: rounds remaining={remaining} <= {force_left}"
            )
            # Nudge model via inject message once
            tc.messages.append({
                "role": "user",
                "content": (
                    "SYSTEM: Round budget nearly exhausted. "
                    "Terminate now with the return tool (required four fields)."
                ),
            })

        answer, should_break, msg = await run_llm_round(
            rnd, model, tc.messages, tc.tools, tc.cache_body, tc.cache_headers,
            base_url, api_key, hooks, tc.ctx, tc.trace, at_ms,
        )
        if should_break:
            break

        tc.messages.append(msg)

        answer, should_break, tc.zeus_headers, outcome = await execute_tool_calls(
            rnd, msg.get("tool_calls") or [], tc.messages,
            api_version, zeus_url, bucket, scope, collection,
            zcfg, tc.zeus_headers, hooks, tc.ctx, tc.trace, at_ms,
            tc.turn_id, conv_id, tc.toon_on, tc.this_turn_reqs,
        )

        # ZC-WISH-044 / Hub: after Zeus tools, cheap vs insight branch
        if outcome.return_seen:
            terminal = (outcome.terminal_summary or answer or "").strip()
            if ai_process:
                # One more no-tools hop to narrate tool JSON (Hub default on).
                synth = await force_final_llm_answer(
                    rnd, model, tc.messages, tc.cache_body, tc.cache_headers,
                    base_url, api_key, hooks, tc.ctx, tc.trace, at_ms,
                    instruction=INSIGHT_AFTER_ZEUS_INSTRUCTION,
                    cause="ai_process_result_insight",
                )
                answer = synth or terminal or answer
                tc.trace["notes"].append(
                    "ai_process_result=true after terminating Zeus tool; insight synthesis"
                )
                tc.trace["ai_process_result_exit"] = "insight"
            else:
                answer = terminal or answer or ""
                if answer and not any(
                    m.get("role") == "assistant" and m.get("content") == answer
                    for m in tc.messages[-3:]
                ):
                    tc.messages.append({"role": "assistant", "content": answer})
                tc.trace["notes"].append(
                    "ai_process_result=false after terminate; cheap terminal envelope"
                )
                tc.trace["ai_process_result_exit"] = "cheap_terminal"
            await hooks.observe("round_end", {
                "round": rnd, "answer_ready": True, "ctx": tc.ctx,
                "ai_process_result": ai_process,
            })
            break

        if (
            not ai_process
            and outcome.tools_executed > 0
            and outcome.tools_with_data > 0
        ):
            # Cheap path (product / MULTI_ROUND wishlist): tools already returned
            # data — do **not** bill a second LLM hop. Hub Debug still force-
            # finals here for operator chat; Client prefers tool-arg summary
            # (pipeline often carries one) or a static thin line so UIs can
            # show Zeus rows without an insight-style essay.
            answer = (
                (outcome.tool_arg_summary or "").strip()
                or CHEAP_FINAL_STATIC_ANSWER
            )
            if not any(
                m.get("role") == "assistant" and m.get("content") == answer
                for m in tc.messages[-3:]
            ):
                tc.messages.append({"role": "assistant", "content": answer})
            tc.trace["notes"].append(
                "ai_process_result=false after Zeus data; thin final without second LLM hop"
            )
            tc.trace["ai_process_result_exit"] = "cheap_final"
            await hooks.observe("round_end", {
                "round": rnd, "answer_ready": True, "ctx": tc.ctx,
                "ai_process_result": False,
            })
            break

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

    # Dual jailbreak score (hooks) — never overwrite model field
    hooks_score = 0.0
    hooks_refuse = False
    try:
        hooks_score = float(hooks.score_jailbreak(tc.ctx) or 0.0)
        hooks_refuse = bool(hooks.must_refuse(tc.ctx))
    except Exception as exc:
        tc.trace["notes"].append(f"hooks_score_failed: {exc}")
    tc.trace["hooks_jailbreak_score"] = hooks_score
    if hooks_refuse:
        tc.trace["notes"].append("hooks: must_refuse=true")

    await hooks.observe("final_answer", {"answer": answer, "ctx": tc.ctx})

    produced_delta = (
        tc.messages[1:][len(prior_turns):] if prior_turns is not None else tc.messages[1:]
    )
    session_meta = await commit_session_turn(
        zeus_url, tc.sid, tc.enable_sessions, tc.this_user_round,
        tc.contract_id, tc.contract_hash, tc.chat_req, produced_delta,
        prior_turns, tc.this_turn_reqs, tc.trace, tc.zeus_headers,
    )
    # Helios cheap spine on session_meta / trace
    if tc.settings:
        session_meta = dict(session_meta or {})
        session_meta.setdefault("ruleset_id", tc.settings.ruleset_id)
        if tc.settings.deployment_id:
            session_meta.setdefault("deployment_id", tc.settings.deployment_id)
        if tc.settings.locale:
            session_meta.setdefault("locale", tc.settings.locale)
        if tc.settings.channel:
            session_meta.setdefault("channel", tc.settings.channel)
        if tc.settings.timezone:
            session_meta.setdefault("timezone", tc.settings.timezone)

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

    # Always run policy path when settings present or structured requested
    want_policy = structured or (tc.settings is not None)
    if want_policy:
        structured_response = extract_structured_response(
            answer, tc.trace, tc.chat_req, output_schema=output_schema,
            settings=tc.settings,
            hooks_jailbreak_score=hooks_score,
            hooks_must_refuse=hooks_refuse,
            apply_policy=True,
        )
        for w in structured_response.warnings:
            tc.trace["notes"].append(f"[WARN] {w}")
        tc.trace["structured_response"] = {
            "zeus_data_count": len(structured_response.zeus_data),
            "entity_type": structured_response.entity_type,
            "source_tool": structured_response.source_tool,
            "policy": structured_response.policy,
            "flags": structured_response.flags,
            "hooks_jailbreak_score": structured_response.hooks_jailbreak_score,
        }
        if structured_response.policy:
            tc.trace["policy"] = structured_response.policy
            tc.trace["control_flags"] = structured_response.flags
            await hooks.observe("policy_decision", {
                "policy": structured_response.policy,
                "flags": structured_response.flags,
                "hooks_jailbreak_score": structured_response.hooks_jailbreak_score,
                "ctx": tc.ctx,
            })
        # Prefer policy UI text for refuse/error
        if structured_response.ui_text and structured_response.policy in ("refuse", "error"):
            answer = structured_response.ui_text
        else:
            layer = structured_response.layer_a or {}
            layer_summary = layer.get("summary") if isinstance(layer, dict) else None
            cleaned = user_facing_answer(
                answer,
                ui_text=structured_response.ui_text,
                layer_summary=layer_summary if isinstance(layer_summary, str) else None,
            )
            if cleaned != (answer or ""):
                answer = cleaned
                structured_response.answer = cleaned
                tc.trace.setdefault("notes", []).append(
                    "peeled Layer A envelope from user-facing answer"
                )
        if structured:
            return answer, tc.trace, tc.messages[1:], session_meta, structured_response

    return answer, tc.trace, tc.messages[1:], session_meta
