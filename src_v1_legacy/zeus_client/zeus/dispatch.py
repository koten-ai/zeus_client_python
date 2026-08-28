"""Zeus V1/V2 tool dispatch."""
import json

import httpx

from zeus_client.constants import TOOL_TIMEOUT, normalize_api_version
from zeus_client.http_client import client
from zeus_client.logging_setup import logger

async def dispatch_zeus_tool(zeus_url, bucket, scope, collection, name, args, zeus_headers, corr_headers=None):
    url = f"{zeus_url}/v1/{bucket}/{scope}/{collection}/tools/{name}"
    headers = {**zeus_headers, "Content-Type": "application/json"}
    # Pin logical scope for FTS/vector stores (mirrors V2 dispatch and
    # Zeus admin chat). The server also derives this from the URL path,
    # but sending the header keeps traces and older Zeus builds honest.
    headers.setdefault("X-Zeus-Scope", f"{bucket}/{scope}")
    if corr_headers:
        for k, v in corr_headers.items():
            headers.setdefault(k, v)
    logger.debug(f"dispatch_zeus_tool: name={name} url={url} args_keys={list(args.keys()) if isinstance(args, dict) else type(args)}")
    try:
        r = await client().post(url, headers=headers, json=args, timeout=TOOL_TIMEOUT)
        req_id = r.headers.get("X-Zeus-Req-Id", "")
        body_preview = (r.text or "")[:300] if r.status_code >= 400 else ""
        logger.debug(f"dispatch_zeus_tool: name={name} -> status={r.status_code} req_id={(req_id or '')[:12]}… bytes={len(r.text or '')}")
        if r.status_code >= 400:
            logger.warning(f"dispatch_zeus_tool: name={name} Zeus error {r.status_code} req={req_id[:12] if req_id else ''} body={body_preview}")
        return r.status_code, r.text, url, req_id
    except httpx.HTTPError as e:
        logger.warning(f"dispatch_zeus_tool: name={name} HTTPError {e}")
        return 0, json.dumps({"error": "dispatch_failed", "message": str(e)}), url, ""


V2_SCOPE_VERBS = {"describe", "analyze"}
V2_BARE_VERBS = {"explain", "return"}


async def dispatch_zeus_v2_verb(
    zeus_url, bucket, scope, collection, name, args, zeus_headers, corr_headers=None, rewind=False,
):
    """Dispatch an OpenAI function named as a V2 verb to the right V2 URL."""
    headers = {**zeus_headers, "Content-Type": "application/json"}
    if name in V2_BARE_VERBS:
        url = f"{zeus_url}/v2/{name}"
    elif name in V2_SCOPE_VERBS:
        url = f"{zeus_url}/v2/{bucket}/{scope}/{name}"
        headers.setdefault("X-Zeus-Scope", f"{bucket}/{scope}")
    elif name == "pipeline":
        # Execute the pipeline. The executor runs the same pre-flight
        # validator internally and returns a structured "rejected"
        # envelope on a bad plan, so the model still gets validation
        # feedback — plus real data on a valid plan. (The validate-only
        # /pipeline/plan endpoint never returns rows, which made the
        # model loop on validation and give up without an answer.)
        url = f"{zeus_url}/v2/{bucket}/{scope}/{collection}/pipeline"
        headers.setdefault("X-Zeus-Scope", f"{bucket}/{scope}")
    else:
        url = f"{zeus_url}/v2/{bucket}/{scope}/{collection}/{name}"
        headers.setdefault("X-Zeus-Scope", f"{bucket}/{scope}")
    if corr_headers:
        for k, v in corr_headers.items():
            headers.setdefault(k, v)
    body = dict(args) if isinstance(args, dict) else args
    if isinstance(body, dict) and "rewind" in body:
        flag = body.pop("rewind")
        if str(flag).strip().lower() in {"1", "true", "yes", "on"} or flag is True:
            rewind = True
    params = {"rewind": "true"} if rewind else None
    logger.debug(f"dispatch_zeus_v2_verb: name={name} url={url} args_keys={list(body.keys()) if isinstance(body, dict) else type(body)}")
    try:
        r = await client().post(url, headers=headers, json=body, timeout=TOOL_TIMEOUT, params=params)
        req_id = r.headers.get("X-Zeus-Req-Id", "")
        body_preview = (r.text or "")[:300] if r.status_code >= 400 else ""
        logger.debug(f"dispatch_zeus_v2_verb: name={name} -> status={r.status_code} req_id={(req_id or '')[:12]}…")
        if r.status_code >= 400:
            logger.warning(f"dispatch_zeus_v2_verb: name={name} Zeus error {r.status_code} req={req_id[:12] if req_id else ''} body={body_preview}")
        return r.status_code, r.text, url, req_id
    except httpx.HTTPError as e:
        logger.warning(f"dispatch_zeus_v2_verb: name={name} HTTPError {e}")
        return 0, json.dumps({"error": "dispatch_failed", "message": str(e)}), url, ""


async def dispatch_zeus_call(
    api_version, zeus_url, bucket, scope, collection, name, args, zeus_headers, corr_headers=None, rewind=False,
):
    if normalize_api_version(api_version) == "v2":
        return await dispatch_zeus_v2_verb(
            zeus_url, bucket, scope, collection, name, args, zeus_headers, corr_headers, rewind=rewind,
        )
    return await dispatch_zeus_tool(zeus_url, bucket, scope, collection, name, args, zeus_headers, corr_headers)


# ── Zeus session + contract + trace (per CHAT_REQUEST_CONTRACT_AND_SESSION_TRACE_IDEA.md) ──
# These implement the durable middle-man contract for external chats:
#   - POST /v2/session  (bind contract_id+hash + chat_request rules + initial conv) → sid + contract_status
#   - GET  /v2/session/{sid}?rounds=N  (scatter/gather rehydrate)
#   - POST /v2/session/{sid}/turn  (CAS+round guard + append immutable shard)
#   - POST /v2/session/trace (delta + join on X-Zeus-Req-Id for Detective attribution)
# Correlation headers (X-Zeus-Chat-Id etc) are sent on every tool dispatch so
# the tracebundle + external traces can be joined in /admin/debug/req/{req_id}.
# contract_status (match|drift|none) is returned on create/trace and recorded
# for ownership (client drift vs zeus fault) in Detective.

def zeus_correlation_headers(
    chat_id: str,
    turn_id: str = "",
    call_id: str = "",
    *,
    mode: str = "",
    force_trace: bool = False,
) -> dict:
    """Build X-Zeus-* correlation headers for tool calls and session/trace.

    ``mode`` stamps ``X-Zeus-Mode`` so TraceBundle envelope/report get a mode
    on paths that MergeEnvelope from logging headers.
    ``force_trace`` sets ``X-Zeus-Trace: 1`` (sampler force-keep; lab/debug).
    """
    h = {}
    if chat_id:
        h["X-Zeus-Chat-Id"] = str(chat_id)
    if turn_id:
        h["X-Zeus-Turn-Id"] = str(turn_id)
    if call_id:
        h["X-Zeus-Call-Id"] = str(call_id)
    if mode:
        h["X-Zeus-Mode"] = str(mode)
    if force_trace:
        h["X-Zeus-Trace"] = "1"
    return h


def apply_zeus_mode_header(headers: dict | None, mode: str | None) -> dict:
    """Return headers with X-Zeus-Mode set when missing and mode is non-empty."""
    h = dict(headers or {})
    m = (mode or "").strip()
    if not m:
        return h
    if "X-Zeus-Mode" not in h and "x-zeus-mode" not in {k.lower() for k in h}:
        h["X-Zeus-Mode"] = m
    return h


def apply_zeus_force_trace_header(headers: dict | None, force: bool) -> dict:
    """Optionally stamp X-Zeus-Trace: 1 for sampler force-keep."""
    h = dict(headers or {})
    if force:
        h["X-Zeus-Trace"] = "1"
    return h
