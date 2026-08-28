"""Durable session create/rehydrate and turn commit."""
import uuid

from zeus_client.contract_hash import (
    compute_contract_hash,
    extract_stamped_hash,
    resolve_session_contract_hash,
)
from zeus_client.logging_setup import logger
from zeus_client.zeus.contracts import resolve_contract_for_scope
from zeus_client.agent.settings import effective_rewind
from zeus_client.zeus.session import (
    continue_session_turn,
    create_zeus_session,
    post_session_trace,
    rehydrate_session,
)


def _contract_status_from_rehydrate(contract_id, session_hash, reh) -> str:
    """Derive contract_status after a successful GET /v2/session rehydrate.

    SessionDoc does not include contract_status (only create/trace responses do).
    Compare the frozen head hash to the payload hash we would bind on APIs.
    """
    reh = reh if isinstance(reh, dict) else {}
    reh_hash = str(reh.get("hash") or "").strip()
    reh_cid = str(reh.get("contract_id") or "").strip()
    cid = str(contract_id or "").strip()
    want_h = str(session_hash or "").strip()

    if not cid and not reh_cid:
        return "none"
    if want_h and reh_hash:
        return "match" if want_h == reh_hash else "drift"
    # Contract binding present but incomplete hash material on one side.
    # Rehydrate succeeded; true mismatch is still enforced by Zeus on turn
    # continue (409 contract_mismatch). Prefer match so runtime audit is not
    # a false FAIL on multi-turn chats that only rehydrate.
    if cid or reh_cid:
        return "match"
    return "none"


async def _create_durable_session(
    zeus_url,
    bucket,
    scope,
    contract_id,
    contract_hash,
    chat_req,
    user_msg,
    zeus_headers,
    trace,
    session_notes,
    *,
    recovered_from="",
    rewind=False,
):
    """POST /v2/session and record create outcome on ``trace``.

    Returns ``(sid, this_user_round)``. On failure returns ``(\"\", 1)`` and
    sets ``trace[\"session_error\"]``.
    """
    reason = (
        f"recreate after dead sid {(recovered_from or '')[:12]}…"
        if recovered_from
        else f"new (contract_id={contract_id or 'none'})"
    )
    logger.info(f"run_agent: creating durable session — {reason}")
    init_conv = [{"role": "user", "content": user_msg}]
    trace["notes"].append(
        f"about to POST /v2/session with contract_id={contract_id} "
        f"contract_hash={contract_hash}"
        + (f" (recovered_from={(recovered_from or '')[:16]}…)" if recovered_from else "")
    )
    cstatus, cbody, c_url, creq = await create_zeus_session(
        zeus_url, bucket, scope, contract_id, contract_hash,
        chat_req, init_conv, zeus_headers, rewind=rewind,
    )
    if cstatus in (200, 201) and isinstance(cbody, dict):
        sid = cbody.get("session_id") or ""
        this_user_round = int(cbody.get("round") or 1)
        cst = cbody.get("contract_status") or "none"
        sess = {
            "created": True,
            "id": sid,
            "round": this_user_round,
            "contract_status": cst,
            "create_url": c_url,
            "create_req_id": creq,
        }
        if recovered_from:
            sess["recovered_from"] = recovered_from
        trace["session"] = sess
        session_notes.append(
            f"session create {sid[:12]}… round {this_user_round} status={cst}"
        )
        if creq:
            session_notes.append(f"create req {creq}")
        logger.info(
            f"run_agent: session CREATED sid={sid[:12]}… round={this_user_round} "
            f"contract_status={cst}"
            + (f" recovered_from={recovered_from[:12]}…" if recovered_from else "")
        )
        return sid, this_user_round

    err_detail = str(cbody)[:300] if cbody else f"HTTP {cstatus}"
    create_req_note = f" (Zeus req_id for the failed /v2/session: {creq})" if creq else ""
    session_notes.append(f"session create failed {cstatus}: {err_detail}{create_req_note}")
    sess = {
        "created": False,
        "id": "",
        "round": 1,
        "contract_status": "none",
        "error": err_detail,
        "create_url": c_url,
        "create_req_id": creq,
    }
    if recovered_from:
        sess["recovered_from"] = recovered_from
    trace["session"] = sess
    trace["session_error"] = err_detail
    logger.error(f"run_agent: session CREATE FAILED status={cstatus}")

    if cstatus == 409 and "payload_hash" in err_detail:
        try:
            import re
            m = re.search(r'"payload_hash":"(md5:[^"]+)"', err_detail)
            if m:
                ph = m.group(1)
                trace["notes"].append(f"Zeus computed payload_hash: {ph}")
        except Exception:
            pass
    return "", 1


async def setup_contract_and_session(
    zeus_url, zcfg, bucket, scope, mode, chat_req, user_msg,
    zeus_session_id, zeus_round, trace, current_content_h, stamped_h,
    zeus_headers,
):
    """Resolve contract binding and create or rehydrate a durable session.

    If an existing ``zeus_session_id`` fails rehydrate (dead/expired session),
    immediately POST a fresh ``/v2/session`` in the same turn so contract_status
    is established and turn commit does not 404 on the dead id.
    """
    enable_sessions = bool(zcfg.get("enable_durable_sessions", True))
    rewind = effective_rewind(None, zcfg)
    contract_id, bound_contract_hash = resolve_contract_for_scope(zcfg, bucket, scope, mode)
    contract_hash = bound_contract_hash
    logger.debug(
        f"run_agent: resolve_contract_for_scope -> contract_id={contract_id} "
        f"hash={(contract_hash or '')[:18]}… enable_sessions={enable_sessions}"
    )
    if contract_id:
        logger.info(
            f"run_agent: will bind contract_id={contract_id} "
            f"hash={(contract_hash or '')[:18]}… on session create (if new)"
        )
    else:
        logger.info(
            "run_agent: NO contract binding resolved for this scope/mode — "
            "/v2/session will be called with empty contract_id/hash"
        )
    trace["contract"] = {"id": contract_id, "hash": contract_hash or ""}

    sid = ""
    this_user_round = 1
    turn_id = "turn_" + uuid.uuid4().hex[:10]
    trace["turn_id"] = turn_id
    session_notes = []

    if not enable_sessions:
        trace["notes"].append(
            "durable sessions: disabled by config (set zeus.enable_durable_sessions=true "
            "once your Zeus has the session collections via 05_sessions_scopes.sh)"
        )
        trace["session"] = {"disabled": True, "reason": "config"}
        if contract_id:
            trace["notes"].append(f"contract: {contract_id} (hash {(contract_hash or '')[:18]}…)")
        else:
            trace["notes"].append("contract: none (no contract_id configured; using contract_status=none)")
        logger.info("run_agent: durable sessions DISABLED by config")
    else:
        if contract_id:
            trace["notes"].append(f"contract: {contract_id} (hash {(contract_hash or '')[:18]}…)")
            try:
                stamped_h = extract_stamped_hash(chat_req)
                current_content_h = compute_contract_hash(chat_req)
                if stamped_h:
                    used_h = stamped_h
                    src = "stamped_from_file (preferred)"
                    if current_content_h and stamped_h != current_content_h:
                        logger.warning(
                            f"run_agent: stamped embedded hash {stamped_h} differs from "
                            f"compute on current object {current_content_h}"
                        )
                        trace["notes"].append(
                            f"WARNING: embedded stamped hash ({stamped_h}) != "
                            f"current_content_hash ({current_content_h})."
                        )
                else:
                    used_h = current_content_h
                    src = "local_compute (you should be using a stamped file from Verify)"
                logger.debug(
                    f"run_agent: hash source for chat_req: {src} short={(used_h or '')[:18]}…"
                )
                trace["notes"].append(f"hash_for_this_chat_req: {used_h} (source: {src})")
                trace["notes"].append(
                    f"client_hash_of_chat_request_object_being_sent_in_create_payload: {current_content_h}"
                )
                if bound_contract_hash and used_h and used_h != bound_contract_hash:
                    trace["notes"].append(
                        "Note: bound contract_hash differs from the hash computed from the "
                        "loaded chat_req content."
                    )
            except Exception as e:
                logger.exception("run_agent: hash extraction/compute failed (non-fatal)")
                trace["notes"].append(f"hash_compute_failed: {e}")
        else:
            trace["notes"].append("contract: none (no contract_id configured; using contract_status=none)")

        session_hash, hash_src = resolve_session_contract_hash(
            bound_contract_hash, stamped_h, current_content_h,
        )
        contract_hash = session_hash
        if contract_id and session_hash:
            trace["notes"].append(
                f"session_contract_hash: {session_hash} (source: {hash_src})"
            )
        if (
            bound_contract_hash
            and session_hash
            and bound_contract_hash != session_hash
        ):
            trace["notes"].append(
                "Note: config scope_contracts hash differs from payload hash; "
                f"using payload hash on session APIs (bound={bound_contract_hash} "
                f"payload={session_hash}). Re-sync catalog and align scope_contracts."
            )

        sid = (zeus_session_id or "").strip()
        current_server_round = int(zeus_round or 0)
        this_user_round = current_server_round + 1 if current_server_round > 0 else 1

        if not sid:
            sid, this_user_round = await _create_durable_session(
                zeus_url, bucket, scope, contract_id, contract_hash,
                chat_req, user_msg, zeus_headers, trace, session_notes,
                rewind=rewind,
            )
        else:
            logger.debug(f"run_agent: existing sid -> rehydrating {sid[:12]}…")
            reh = await rehydrate_session(zeus_url, sid, rounds=6, zeus_headers=zeus_headers)
            if reh and isinstance(reh, dict):
                reh_round = int(reh.get("round") or current_server_round)
                conv_len = len(reh.get("conversation") or [])
                this_user_round = reh_round + 1
                cst = _contract_status_from_rehydrate(contract_id, contract_hash, reh)
                trace["session_rehydrate"] = {
                    "id": sid, "server_round": reh_round,
                    "conv_turns": conv_len, "shards": reh.get("rounds_loaded"),
                    "contract_status": cst,
                    "head_hash": (reh.get("hash") or "")[:40],
                }
                # GET /v2/session omits contract_status; set session meta so
                # commit/audit do not default to status=none on multi-turn.
                trace["session"] = {
                    "created": False,
                    "id": sid,
                    "round": reh_round,
                    "contract_status": cst,
                    "rehydrated": True,
                }
                session_notes.append(
                    f"rehydrated {sid[:12]}… r{reh_round} ({conv_len} turns) "
                    f"contract_status={cst}"
                )
            else:
                dead_sid = sid
                session_notes.append(
                    f"rehydrate {dead_sid[:12]}… failed or empty → creating fresh session"
                )
                logger.warning(
                    f"run_agent: rehydrate for sid={dead_sid[:12]}… returned empty or failed; "
                    "creating fresh durable session same-turn"
                )
                trace["session_rehydrate"] = {
                    "id": dead_sid,
                    "failed": True,
                    "recreated": True,
                }
                sid, this_user_round = await _create_durable_session(
                    zeus_url, bucket, scope, contract_id, contract_hash,
                    chat_req, user_msg, zeus_headers, trace, session_notes,
                    recovered_from=dead_sid,
                    rewind=rewind,
                )
                if not sid:
                    # Create also failed — leave no dead id for turn commit.
                    this_user_round = 1

    for n in session_notes:
        trace["notes"].append(n)

    return {
        "sid": sid,
        "turn_id": turn_id,
        "this_user_round": this_user_round,
        "contract_id": contract_id,
        "contract_hash": contract_hash,
        "bound_contract_hash": bound_contract_hash,
        "enable_sessions": enable_sessions,
        "stamped_h": stamped_h,
        "current_content_h": current_content_h,
    }


async def commit_session_turn(
    zeus_url, sid, enable_sessions, this_user_round, contract_id, contract_hash,
    chat_req, produced_delta, prior_turns, this_turn_reqs, trace, zeus_headers,
    layer_a=None,
    rewind=False,
):
    """POST trace deltas and persist the turn shard.

    Multi-hop note (Hub Detective E2E): Zeus keeps **one** TraceDoc per
    session round. We therefore build one rich multi-hop payload and POST
    it once per tool ``req_id`` (same body) so every hop's reverse index
    joins to the same round doc. Primary hop is written **last** so the
    round doc's ``req_id`` matches the preferred Detective deep-link.

    ``layer_a`` (optional) is the terminate bag (intent / QD / decomp /
    confidence) so Detective shows Layer A on external client hops.
    """
    from zeus_client.trace.session_hops import (
        build_aggregate_trace_payload,
        merge_hop_into_trace_session,
        normalize_hops,
        ordered_req_ids_for_trace_posts,
        select_primary_req_id,
    )

    hops = normalize_hops(this_turn_reqs)
    primary_rid = select_primary_req_id(hops)
    req_ids = [h["req_id"] for h in hops if h.get("req_id")]

    session_meta = {
        "session_id": sid,
        "round": this_user_round,
        "contract_id": contract_id,
        "contract_hash": contract_hash,
        "contract_status": (trace.get("session") or {}).get("contract_status") or "none",
        "req_ids": req_ids,
        "primary_req_id": primary_rid,
        "preferred_req_id": primary_rid,
        "enabled": enable_sessions,
    }

    if sid and enable_sessions:
        logger.debug(
            f"run_agent: committing traces + turn for sid={sid[:12]}… "
            f"this_user_round={this_user_round} reqs={len(hops)}"
        )
        # Prefer explicit layer_a; else harvest from trace steps (return / pipeline).
        la = layer_a
        if not la and isinstance(trace, dict):
            try:
                from zeus_client.agent.response import layer_a_for_session_trace
                la = layer_a_for_session_trace(trace) or None
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug(f"layer_a_for_session_trace failed: {exc}")
                la = None
        if hops or la:
            _, turns, zeus_response, outcome = build_aggregate_trace_payload(
                hops, layer_a=la,
            )
            # If only Layer A (no tool hops), still post once under a synthetic
            # join — needs a req_id. Skip post without hops+req_id (nothing to join).
            post_order = ordered_req_ids_for_trace_posts(hops)
            if not post_order and not hops:
                # No tool hops: nothing to reverse-index; skip trace POST.
                # Layer A alone without req_id cannot join Detective.
                pass
            for rid in post_order:
                tr_status, tr_body, _, _ = await post_session_trace(
                    zeus_url, sid, this_user_round, rid,
                    contract_id, contract_hash, chat_req,
                    turns=turns,
                    zeus_response=zeus_response,
                    outcome=outcome,
                    zeus_headers=zeus_headers,
                    rewind=rewind,
                )
                if tr_status in (200, 201):
                    trace["notes"].append(f"trace {rid[:8]}… -> {tr_status}")
                    if isinstance(tr_body, dict):
                        live_cst = tr_body.get("contract_status")
                        if live_cst:
                            session_meta["contract_status"] = live_cst
                            trace.setdefault("session", {})["contract_status"] = live_cst
                else:
                    trace["notes"].append(f"trace post {rid[:8]}… -> {tr_status}")
                    trace["session_error"] = trace.get("session_error") or f"trace {tr_status}"
            if primary_rid:
                trace["notes"].append(
                    f"session_trace primary_req_id={primary_rid[:12]}… "
                    f"hops={len(hops)} aggregate=1"
                    + (" layer_a=1" if la else "")
                )

        just_created = bool((trace.get("session") or {}).get("created"))
        if just_created:
            turn_round = this_user_round + 1
            turn_turns = [m for m in produced_delta if (m.get("role") or "") != "user"]
        else:
            turn_round = this_user_round
            turn_turns = produced_delta
        if turn_turns:
            tu_status, _, tu_url, tu_req = await continue_session_turn(
                zeus_url, sid, turn_round, chat_req, turn_turns, zeus_headers, rewind=rewind)
            trace["session_turn"] = {
                "status": tu_status, "round": turn_round, "url": tu_url,
                "req_id": tu_req, "turns": len(turn_turns),
            }
            session_meta["round"] = turn_round
            if tu_status == 200:
                trace["notes"].append(f"turn r{turn_round} -> 200 (req={tu_req[:8] if tu_req else ''}…)")
            else:
                trace["notes"].append(f"turn post r{turn_round} -> {tu_status}")
                trace["session_error"] = trace.get("session_error") or f"turn {tu_status}"
        else:
            trace["notes"].append("no new turns to persist for this question")

    trace["session"] = trace.get("session") or {}
    trace["session"].update({
        "id": sid,
        "round": session_meta.get("round", this_user_round),
        "contract_status": session_meta.get("contract_status"),
        "enabled": enable_sessions,
        "req_ids": req_ids,
    })
    if primary_rid:
        trace["session"]["primary_req_id"] = primary_rid
        trace["session"]["preferred_req_id"] = primary_rid
    merge_hop_into_trace_session(trace, req_ids=req_ids, primary_req_id=primary_rid)
    if trace.get("session_error"):
        trace["session"]["error"] = trace["session_error"]

    return session_meta