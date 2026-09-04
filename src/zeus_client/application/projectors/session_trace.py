"""Multi-hop session-trace projector (ZCM-006 · Hub Detective join).

Zeus stores **one** TraceDoc per session round. Posting different tool hops
with the same round overwrites that doc. Algorithm (locked):

1. Build one rich multi-hop ``zeus_response`` + ``turns`` payload.
2. POST ``/v2/session/trace`` once per hop with that **identical** body,
   ``req_id`` = that hop (updates the reverse index).
3. Post the **primary** hop **last** so the round doc's ``req_id`` matches
   the preferred Detective deep-link.

Primary ranking: error > rows > find/search > non-pipeline.
Projectors soft-fail — never raise out of a successful domain turn.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Union

from zeus_client.adapters.zeus_http.session import HttpxSessionClient
from zeus_client.domain.session import SessionHandle

__all__ = [
    "TRACE_SNIPPET_MAX",
    "AggregateTracePayload",
    "SessionTraceProjectResult",
    "normalize_hop",
    "normalize_hops",
    "select_primary_hop",
    "select_primary_req_id",
    "ordered_req_ids_for_trace_posts",
    "build_aggregate_trace_payload",
    "extract_pipeline_meta",
    "merge_hop_into_trace_session",
    "project_session_trace",
]

# Longer than the historical 300-char client snip so Detective session
# panel can show step_costs / empty-result signals without re-running.
TRACE_SNIPPET_MAX = 2000

# Hop record shape used by tool_round → commit. Legacy 5-tuples accepted.
HopLike = Union[Mapping[str, Any], Sequence[Any], tuple]


@dataclass(frozen=True, slots=True)
class AggregateTracePayload:
    """Typed aggregate for one session round (identical body per hop post)."""

    primary_req_id: str | None
    turns: tuple[dict[str, str], ...]
    zeus_response: Mapping[str, Any]
    outcome: str


@dataclass(frozen=True, slots=True)
class SessionTraceProjectResult:
    """Outcome of posting multi-hop session-trace (soft-fail friendly)."""

    ok: bool
    primary_req_id: str | None
    preferred_req_id: str | None
    post_order: tuple[str, ...]
    posts: int
    errors: tuple[str, ...] = ()
    contract_status: str | None = None
    aggregate: Mapping[str, Any] = field(default_factory=dict)


def _status_ok(status: Any) -> bool:
    if status is None:
        return True
    if isinstance(status, int):
        return 0 < status < 400
    s = str(status).lower()
    return s in {"ok", "200", "201", "204"}


def normalize_hop(raw: HopLike) -> dict[str, Any]:
    """Normalize a hop tuple/dict into a stable dict."""
    if isinstance(raw, Mapping):
        rid = str(raw.get("req_id") or "").strip()
        name = str(raw.get("name") or raw.get("verb") or "").strip()
        status = raw.get("status", raw.get("tstatus"))
        snip = raw.get("snippet")
        if snip is None:
            snip = raw.get("result_text") or raw.get("snip") or ""
        snip = str(snip or "")
        if len(snip) > TRACE_SNIPPET_MAX:
            snip = snip[:TRACE_SNIPPET_MAX]
        url = str(raw.get("url") or raw.get("dispatch_url") or "")
        ms = raw.get("ms")
        try:
            ms_i = int(ms) if ms is not None else None
        except (TypeError, ValueError):
            ms_i = None
        hop: dict[str, Any] = {
            "req_id": rid,
            "name": name,
            "status": status,
            "snippet": snip,
            "url": url,
        }
        if ms_i is not None:
            hop["ms"] = ms_i
        for key in (
            "step_costs",
            "result_size",
            "pipeline_status",
            "steps_executed",
            "bytes",
            "error",
        ):
            if raw.get(key) is not None:
                hop[key] = raw[key]
        return hop

    # Legacy tuple: (req_id, name, status, snippet, url[, ms, ...])
    seq = list(raw) if raw is not None else []
    rid = str(seq[0] if len(seq) > 0 else "" or "").strip()
    name = str(seq[1] if len(seq) > 1 else "" or "").strip()
    status = seq[2] if len(seq) > 2 else None
    snip = str(seq[3] if len(seq) > 3 else "" or "")
    if len(snip) > TRACE_SNIPPET_MAX:
        snip = snip[:TRACE_SNIPPET_MAX]
    url = str(seq[4] if len(seq) > 4 else "" or "")
    hop = {
        "req_id": rid,
        "name": name,
        "status": status,
        "snippet": snip,
        "url": url,
    }
    if len(seq) > 5 and seq[5] is not None:
        try:
            hop["ms"] = int(seq[5])
        except (TypeError, ValueError):
            pass
    return hop


def normalize_hops(raw_hops: Sequence[HopLike] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_hops or []:
        hop = normalize_hop(raw)
        rid = hop.get("req_id") or ""
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(hop)
    return out


def _result_size_of(hop: Mapping[str, Any]) -> int | None:
    if hop.get("result_size") is not None:
        try:
            return int(hop["result_size"])
        except (TypeError, ValueError):
            pass
    costs = hop.get("step_costs")
    if isinstance(costs, list) and costs:
        total = 0
        any_sz = False
        for c in costs:
            if isinstance(c, Mapping) and c.get("result_size") is not None:
                try:
                    total += int(c["result_size"])
                    any_sz = True
                except (TypeError, ValueError):
                    pass
        if any_sz:
            return total
    return None


def _hop_score(hop: Mapping[str, Any]) -> tuple:
    """Higher is better for primary session-trace / preferred deep-link."""
    name = str(hop.get("name") or "").lower()
    status = hop.get("status")
    ok = _status_ok(status)
    err = 1 if not ok else 0
    is_pipeline = 1 if name == "pipeline" else 0
    is_search_find = (
        1
        if name
        in {
            "search",
            "find",
            "find_nodes",
            "text_search",
            "hybrid_search",
            "project",
            "get",
            "get_by_keys",
        }
        else 0
    )
    sz = _result_size_of(hop)
    has_rows = 1 if (sz is not None and sz > 0) else 0
    has_costs = 1 if hop.get("step_costs") else 0
    has_body = 1 if (hop.get("snippet") or hop.get("bytes")) else 0
    # error hops first, then hops with rows, then search/find, then non-pipeline
    return (
        err,
        has_rows,
        is_search_find,
        has_costs,
        has_body,
        0 if is_pipeline else 1,
    )


def select_primary_hop(hops: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Pick the best hop for TraceDoc.req_id / Detective deep-link."""
    ranked = [h for h in hops if h.get("req_id")]
    if not ranked:
        return None
    ranked.sort(key=_hop_score, reverse=True)
    return dict(ranked[0])


def select_primary_req_id(hops: Sequence[HopLike] | None) -> str | None:
    norm = normalize_hops(hops)
    primary = select_primary_hop(norm)
    return str(primary["req_id"]) if primary else None


def _turn_line(hop: Mapping[str, Any]) -> str:
    name = hop.get("name") or "tool"
    status = hop.get("status")
    parts = [f"{name} → {status}"]
    if hop.get("ms") is not None:
        parts.append(f"{hop['ms']}ms")
    sz = _result_size_of(hop)
    if sz is not None:
        parts.append(f"result_size={sz}")
    costs = hop.get("step_costs")
    if isinstance(costs, list) and costs:
        parts.append(f"steps={len(costs)}")
        brief = []
        for c in costs[:8]:
            if not isinstance(c, Mapping):
                continue
            a = c.get("as") or c.get("name") or "?"
            st = c.get("status") or "ok"
            rs = c.get("result_size")
            if rs is not None:
                brief.append(f"{a}:{st}:{rs}")
            else:
                brief.append(f"{a}:{st}")
        if brief:
            parts.append("[" + ", ".join(brief) + "]")
    if hop.get("error"):
        parts.append(f"err={str(hop['error'])[:120]}")
    elif not _status_ok(status) and hop.get("snippet"):
        parts.append(str(hop["snippet"])[:120])
    return " · ".join(parts)


def build_aggregate_trace_payload(
    hops: Sequence[HopLike] | None,
    *,
    layer_a: Mapping[str, Any] | None = None,
    inject: Mapping[str, Any] | None = None,
    tokens: Mapping[str, Any] | None = None,
    stamp: Mapping[str, Any] | None = None,
) -> AggregateTracePayload:
    """Build typed aggregate for one round (identical body for every hop post)."""
    norm = normalize_hops(hops)
    if not norm:
        z: dict[str, Any] = {}
        if layer_a:
            z["layer_a"] = dict(layer_a)
        if inject:
            z["inject"] = dict(inject)
        if tokens:
            z["tokens"] = dict(tokens)
        if stamp:
            z.update({k: v for k, v in dict(stamp).items() if v is not None})
        return AggregateTracePayload(
            primary_req_id=None,
            turns=(),
            zeus_response=z,
            outcome="ok",
        )

    primary = select_primary_hop(norm)
    primary_rid = str(primary["req_id"]) if primary else norm[0]["req_id"]

    turns = tuple({"role": "tool", "content": _turn_line(h)} for h in norm)

    any_err = any(not _status_ok(h.get("status")) for h in norm)
    outcome = "error" if any_err else "ok"

    hop_summaries = []
    for h in norm:
        entry: dict[str, Any] = {
            "req_id": h.get("req_id"),
            "name": h.get("name"),
            "status": h.get("status"),
            "url": h.get("url"),
            "primary": h.get("req_id") == primary_rid,
        }
        if h.get("ms") is not None:
            entry["ms"] = h["ms"]
        sz = _result_size_of(h)
        if sz is not None:
            entry["result_size"] = sz
        if h.get("step_costs") is not None:
            entry["step_costs"] = h["step_costs"]
        if h.get("pipeline_status") is not None:
            entry["pipeline_status"] = h["pipeline_status"]
        if h.get("steps_executed") is not None:
            entry["steps_executed"] = h["steps_executed"]
        if h.get("error"):
            entry["error"] = h["error"]
        if h.get("snippet"):
            entry["snippet"] = h["snippet"]
        hop_summaries.append(entry)

    # Primary hop fields at top-level for older Detective UIs.
    prim = primary or norm[0]
    zeus_response: dict[str, Any] = {
        "status": prim.get("status"),
        "url": prim.get("url") or "",
        "snippet": prim.get("snippet") or "",
        "primary_req_id": primary_rid,
        "req_ids": [h["req_id"] for h in norm],
        "tool_hops": hop_summaries,
        "hop_count": len(norm),
        "aggregate": True,
    }
    if prim.get("ms") is not None:
        zeus_response["ms"] = prim["ms"]
    if prim.get("step_costs") is not None:
        zeus_response["step_costs"] = prim["step_costs"]
    sz = _result_size_of(prim)
    if sz is not None:
        zeus_response["result_size"] = sz
    if layer_a:
        zeus_response["layer_a"] = dict(layer_a)
    if inject:
        zeus_response["inject"] = dict(inject)
    if tokens:
        zeus_response["tokens"] = dict(tokens)
    if stamp:
        for k, v in dict(stamp).items():
            if v is not None:
                zeus_response.setdefault(k, v)

    return AggregateTracePayload(
        primary_req_id=primary_rid,
        turns=turns,
        zeus_response=zeus_response,
        outcome=outcome,
    )


def ordered_req_ids_for_trace_posts(hops: Sequence[HopLike] | None) -> list[str]:
    """Req ids to POST: secondaries first, primary last (round doc req_id)."""
    norm = normalize_hops(hops)
    if not norm:
        return []
    primary = select_primary_hop(norm)
    primary_rid = primary["req_id"] if primary else norm[-1]["req_id"]
    secondaries = [h["req_id"] for h in norm if h["req_id"] != primary_rid]
    return secondaries + [primary_rid]


def extract_pipeline_meta(parsed: Any) -> dict[str, Any]:
    """Pull compact pipeline fields from a parsed tool JSON body."""
    out: dict[str, Any] = {}
    if not isinstance(parsed, Mapping):
        return out
    meta = parsed.get("meta")
    data = parsed.get("data")
    if not isinstance(meta, Mapping) and isinstance(data, Mapping):
        meta = data.get("meta")
        if parsed.get("status") is not None:
            out["pipeline_status"] = parsed.get("status")
    if isinstance(meta, Mapping):
        costs = meta.get("step_costs")
        if isinstance(costs, list):
            out["step_costs"] = costs
            total = 0
            any_sz = False
            for c in costs:
                if isinstance(c, Mapping) and c.get("result_size") is not None:
                    try:
                        total += int(c["result_size"])
                        any_sz = True
                    except (TypeError, ValueError):
                        pass
            if any_sz:
                out["result_size"] = total
        if meta.get("steps_executed") is not None:
            out["steps_executed"] = meta.get("steps_executed")
        if meta.get("elapsed_ms") is not None and "ms" not in out:
            try:
                out.setdefault("ms_meta", int(meta["elapsed_ms"]))
            except (TypeError, ValueError):
                pass
    if parsed.get("status") is not None and "pipeline_status" not in out:
        st = parsed.get("status")
        if isinstance(st, str):
            out["pipeline_status"] = st
    result = parsed.get("result") if isinstance(parsed.get("result"), Mapping) else None
    if result is not None:
        rc = result.get("returned_count")
        if rc is None and isinstance(result.get("items"), list):
            rc = len(result["items"])
        if rc is None and isinstance(result.get("node_ids"), list):
            rc = len(result["node_ids"])
        if rc is not None:
            try:
                out.setdefault("result_size", int(rc))
            except (TypeError, ValueError):
                pass
    if parsed.get("error") and not out.get("error"):
        err = parsed.get("error")
        if isinstance(err, Mapping):
            out["error"] = err.get("message") or err.get("code") or str(err)
        else:
            out["error"] = str(err)
    msg = parsed.get("message")
    if parsed.get("error") and isinstance(msg, str) and "error" not in out:
        out["error"] = msg
    return out


def merge_hop_into_trace_session(
    trace: MutableMapping[str, Any],
    *,
    req_ids: Sequence[str],
    primary_req_id: str | None,
) -> None:
    """Stamp multi-hop ids onto trace['session'] for client Detective consumers."""
    sess = trace.setdefault("session", {})
    if not isinstance(sess, dict):
        return
    sess["req_ids"] = list(req_ids)
    if primary_req_id:
        sess["primary_req_id"] = primary_req_id
        sess["preferred_req_id"] = primary_req_id


async def project_session_trace(
    client: HttpxSessionClient,
    *,
    handle: SessionHandle,
    hops: Sequence[HopLike] | None,
    chat_request: Mapping[str, Any] | None = None,
    layer_a: Mapping[str, Any] | None = None,
    inject: Mapping[str, Any] | None = None,
    tokens: Mapping[str, Any] | None = None,
    stamp: Mapping[str, Any] | None = None,
    mode: str = "analytics",
    headers: Mapping[str, str] | None = None,
    rewind: bool = False,
    turn_id: str = "",
) -> SessionTraceProjectResult:
    """POST identical multi-hop aggregate once per req_id (primary last).

    Soft-fail: never raises; returns ``ok=False`` with error strings on hop
    post failures so the agent turn can still complete.
    """
    if not handle.enabled or not handle.session_id:
        return SessionTraceProjectResult(
            ok=True,
            primary_req_id=None,
            preferred_req_id=None,
            post_order=(),
            posts=0,
        )

    agg = build_aggregate_trace_payload(
        hops, layer_a=layer_a, inject=inject, tokens=tokens, stamp=stamp
    )
    post_order = ordered_req_ids_for_trace_posts(hops)
    if not post_order:
        return SessionTraceProjectResult(
            ok=True,
            primary_req_id=agg.primary_req_id,
            preferred_req_id=agg.primary_req_id,
            post_order=(),
            posts=0,
            aggregate=dict(agg.zeus_response),
        )

    errors: list[str] = []
    posts = 0
    live_cst: str | None = handle.contract_status or None
    turns = list(agg.turns)
    zresp = dict(agg.zeus_response)

    for rid in post_order:
        try:
            result = await client.post_trace(
                session_id=handle.session_id,
                client_round=int(handle.round),
                req_id=rid,
                contract_id=handle.contract_id,
                contract_hash=handle.contract_hash,
                chat_request=chat_request or {},
                turns=turns,
                zeus_response=zresp,
                outcome=agg.outcome,
                headers=headers,
                mode=mode,
                rewind=rewind,
                turn_id=turn_id,
            )
            if result.ok:
                posts += 1
                if isinstance(result.body, Mapping):
                    cst = result.body.get("contract_status")
                    if cst:
                        live_cst = str(cst)
            else:
                errors.append(
                    f"trace {rid} -> {result.status_code}: "
                    f"{(result.error or str(result.body)[:120])}"
                )
        except Exception as e:  # pragma: no cover — defensive soft-fail
            errors.append(f"trace {rid} exception: {e}")

    return SessionTraceProjectResult(
        ok=not errors,
        primary_req_id=agg.primary_req_id,
        preferred_req_id=agg.primary_req_id,
        post_order=tuple(post_order),
        posts=posts,
        errors=tuple(errors),
        contract_status=live_cst,
        aggregate=zresp,
    )
