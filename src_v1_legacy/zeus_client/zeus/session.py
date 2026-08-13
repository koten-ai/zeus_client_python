"""Zeus durable session + trace APIs."""
import json

import httpx

from zeus_client.constants import TOOL_TIMEOUT
from zeus_client.http_client import client
from zeus_client.logging_setup import logger

async def create_zeus_session(zeus_url, bucket, scope, contract_id, contract_hash,
                              chat_request, initial_conversation, zeus_headers):
    """Phase C: open a durable session (round 1 head + shard). Returns
    (status, body_or_text, url, req_id). On success body contains
    session_id, round, hash, contract_status, max_rounds."""
    # Durable session routes are V2-only (Zeus RELEASE_NOTES ZE-35).
    url = f"{zeus_url}/v2/session"
    payload = {
        "contract_id": contract_id or "",
        "contract_hash": contract_hash or "",
        "chat_request": chat_request or {},
        "conversation": initial_conversation or [],
    }
    headers = {**zeus_headers, "Content-Type": "application/json"}
    logger.debug(f"create_zeus_session: url={url} contract_id={contract_id} hash={(contract_hash or '')[:18]}… conv_len={len(initial_conversation or [])}")
    try:
        r = await client().post(url, headers=headers, json=payload, timeout=TOOL_TIMEOUT)
        req_id = r.headers.get("X-Zeus-Req-Id", "")
        logger.debug(f"create_zeus_session: -> {r.status_code} req_id={(req_id or '')[:12]}…")
        if r.status_code in (200, 201):
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            body = dict(body) if isinstance(body, dict) else {"raw": body}
            body["_req_id"] = req_id
            return r.status_code, body, url, req_id
        logger.warning(f"create_zeus_session: non-2xx {r.status_code} body[:200]={ (r.text or '')[:200] }")
        return r.status_code, (r.text or ""), url, req_id
    except httpx.HTTPError as e:
        logger.error(f"create_zeus_session: exception {e}")
        return 0, json.dumps({"error": "session_create_failed", "message": str(e)}), url, ""


async def continue_session_turn(zeus_url, session_id, client_round, chat_request,
                                new_turns, zeus_headers):
    """Phase D4: persist a round shard (client_round must be server+1).
    new_turns are the delta turns (user + assistant/tool) for this user question."""
    if not session_id:
        logger.warning("continue_session_turn: called with empty session_id")
        return 0, "no session_id", "", ""
    url = f"{zeus_url}/v2/session/{session_id}/turn"
    payload = {
        "round": int(client_round),
        "chat_request": chat_request or {},
        "new_turns": new_turns or [],
    }
    headers = {**zeus_headers, "Content-Type": "application/json"}
    logger.debug(f"continue_session_turn: sid={(session_id or '')[:12]}… round={client_round} new_turns={len(new_turns or [])}")
    try:
        r = await client().post(url, headers=headers, json=payload, timeout=TOOL_TIMEOUT)
        req_id = r.headers.get("X-Zeus-Req-Id", "")
        logger.debug(f"continue_session_turn: -> {r.status_code} req={(req_id or '')[:12]}…")
        if r.status_code == 200:
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            body = dict(body) if isinstance(body, dict) else {"raw": body}
            body["_req_id"] = req_id
            return r.status_code, body, url, req_id
        logger.warning(f"continue_session_turn non-200: {r.status_code}")
        return r.status_code, (r.text or ""), url, req_id
    except httpx.HTTPError as e:
        logger.error(f"continue_session_turn exception: {e}")
        return 0, json.dumps({"error": "session_turn_failed", "message": str(e)}), url, ""


async def post_session_trace(zeus_url, session_id, client_round, req_id,
                             contract_id, contract_hash, chat_request,
                             turns, zeus_response, outcome, zeus_headers):
    """Phase D5: post a per-round (or per-req) trace delta joined to req_id.
    Enables Detective /admin/debug/req/{req_id} to show external session
    panel + contract_status attribution (drift vs zeus_fault)."""
    if not session_id or client_round <= 0:
        logger.warning("post_session_trace: bad params (no sid or round<=0)")
        return 0, "bad trace params", "", ""
    url = f"{zeus_url}/v2/session/trace"
    payload = {
        "session_id": session_id,
        "round": int(client_round),
        "req_id": req_id or "",
        "contract_id": contract_id or "",
        "contract_hash": contract_hash or "",
        "chat_request": chat_request or {},
        "turns": turns or [],
        "zeus_response": zeus_response or {},
        "outcome": outcome or "ok",
    }
    headers = {**zeus_headers, "Content-Type": "application/json"}
    logger.debug(f"post_session_trace: sid={(session_id or '')[:12]}… round={client_round} join_req={(req_id or '')[:12]}…")
    try:
        r = await client().post(url, headers=headers, json=payload, timeout=TOOL_TIMEOUT)
        trace_req_id = r.headers.get("X-Zeus-Req-Id", "")
        logger.debug(f"post_session_trace: -> {r.status_code} trace_req={(trace_req_id or '')[:12]}…")
        if r.status_code in (200, 201):
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            body = dict(body) if isinstance(body, dict) else {"raw": body}
            body["_req_id"] = trace_req_id
            return r.status_code, body, url, trace_req_id
        logger.warning(f"post_session_trace non-success: {r.status_code}")
        return r.status_code, (r.text or ""), url, trace_req_id
    except httpx.HTTPError as e:
        logger.error(f"post_session_trace exception: {e}")
        return 0, json.dumps({"error": "session_trace_failed", "message": str(e)}), url, ""


async def rehydrate_session(zeus_url, session_id, rounds=6, zeus_headers=None):
    """Phase D1: cheap rehydrate via scatter/gather of last N round shards.
    Returns the aggregated SessionDoc (with Conversation list) or None."""
    if not session_id:
        return None
    url = f"{zeus_url}/v2/session/{session_id}?rounds={int(rounds)}"
    headers = zeus_headers or {}
    try:
        r = await client().get(url, headers=headers, timeout=TOOL_TIMEOUT)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None
    except httpx.HTTPError:
        pass
    return None
