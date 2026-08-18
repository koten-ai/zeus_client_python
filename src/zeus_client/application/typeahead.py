"""Typeahead search use-case — Direct only, FTS default (ZCM-012/031).

Public name is ``search`` (not ``fast_suggest``). Never calls the agent loop.
Optional N1QL hydrate only when explicitly configured (no implicit :8093).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zeus_client.adapters.zeus_http.headers import (
    TRACE_CLASS_DIRECT_INTERACTIVE,
    correlation_headers,
)
from zeus_client.config.models import DataTarget
from zeus_client.ports import VerbRequest
from zeus_client.ports.zeus import ZeusPort

__all__ = [
    "SuggestHit",
    "SuggestResult",
    "SuggestOptions",
    "merge_hits",
    "src_keys_from_fts_payload",
    "run_typeahead_search",
]

DEFAULT_LIMIT = 8
MIN_QUERY_LEN = 2
DEFAULT_FTS_TIMEOUT_MS = 2000
DEFAULT_ENTITY_TYPE = "Business"


@dataclass(frozen=True, slots=True)
class SuggestHit:
    id: str
    name: str
    subtitle: str = ""
    city: str = ""
    state: str = ""
    stars: float | None = None
    review_count: int | None = None
    categories: str = ""
    address: str = ""
    score: float | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "subtitle": self.subtitle,
            "city": self.city,
            "state": self.state,
            "stars": self.stars,
            "review_count": self.review_count,
            "categories": self.categories,
            "address": self.address,
            "score": self.score,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class SuggestResult:
    query: str
    hits: tuple[SuggestHit, ...]
    count: int
    source: str
    sources: tuple[str, ...]
    fts_req_id: str = ""
    error: str = ""
    fast_tier: bool = True
    ai_process_result: bool = False
    req_ids: tuple[str, ...] = ()
    trace_class: str = TRACE_CLASS_DIRECT_INTERACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [h.to_dict() for h in self.hits],
            "hits": [h.to_dict() for h in self.hits],
            "count": self.count,
            "source": self.source,
            "sources": list(self.sources),
            "fts_req_id": self.fts_req_id or None,
            "error": self.error or None,
            "fast_tier": self.fast_tier,
            "ai_process_result": self.ai_process_result,
            "req_ids": list(self.req_ids),
            "trace_class": self.trace_class,
        }


@dataclass(frozen=True, slots=True)
class SuggestOptions:
    entity_type: str = DEFAULT_ENTITY_TYPE
    limit: int = DEFAULT_LIMIT
    min_query_len: int = MIN_QUERY_LEN
    fts_timeout_ms: int = DEFAULT_FTS_TIMEOUT_MS
    # Hybrid is never the typeahead default (TEI-dependent).
    strategy: str = "fts"
    mode_header: str = "analytics"
    # Reserved: only when caller passes couchbase config (Phase 3.2+ polish).
    use_n1ql_hydrate: bool = False


def _norm_id(value: str) -> str:
    s = (value or "").strip().lower()
    if s.startswith("biz:"):
        s = s[4:]
    return s


def merge_hits(*groups: Sequence[SuggestHit], limit: int) -> list[SuggestHit]:
    """Dedupe by normalized id then name; preserve first-seen order (FTS first)."""
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    out: list[SuggestHit] = []
    for group in groups:
        for hit in group:
            nid = _norm_id(hit.id)
            nname = (hit.name or "").strip().lower()
            if nid and nid in seen_ids:
                continue
            if nname and nname in seen_names:
                continue
            if nid:
                seen_ids.add(nid)
            if nname:
                seen_names.add(nname)
            out.append(hit)
            if len(out) >= limit:
                return out
    return out


def _result_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, dict):
        items = result.get("items")
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
    return []


def src_keys_from_fts_payload(payload: Mapping[str, Any]) -> list[str]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    keys = result.get("src_keys") if isinstance(result, dict) else None
    out: list[str] = []
    if isinstance(keys, list):
        for k in keys:
            s = str(k or "").strip()
            if s:
                out.append(s)
    if out:
        return list(dict.fromkeys(out))
    for item in _result_items(payload):
        node = item.get("node") if isinstance(item.get("node"), dict) else item
        if not isinstance(node, dict):
            continue
        for key in ("doc_key", "source", "id", "key", "name"):
            s = str(node.get(key) or "").strip()
            if s and key != "name":
                out.append(s)
                break
    return list(dict.fromkeys(out))


def _hits_from_fts(payload: Mapping[str, Any], *, source: str = "fts") -> list[SuggestHit]:
    hits: list[SuggestHit] = []
    for item in _result_items(payload):
        node = item.get("node") if isinstance(item.get("node"), dict) else item
        if not isinstance(node, dict):
            continue
        hid = ""
        for key in ("doc_key", "source", "id", "key"):
            hid = str(node.get(key) or "").strip()
            if hid:
                break
        name = str(node.get("name") or hid or "").strip()
        score = None
        try:
            if item.get("score") is not None:
                score = float(item["score"])
        except (TypeError, ValueError):
            score = None
        hits.append(
            SuggestHit(
                id=hid or name,
                name=name or hid,
                city=str(node.get("city") or ""),
                state=str(node.get("state") or ""),
                subtitle=str(node.get("city") or node.get("categories") or ""),
                score=score,
                source=source,
            )
        )
    if hits:
        return hits
    # Fallback: keys only
    for k in src_keys_from_fts_payload(payload):
        hits.append(SuggestHit(id=k, name=k, source=source))
    return hits


async def run_typeahead_search(
    zeus: ZeusPort,
    query: str,
    *,
    target: DataTarget,
    options: SuggestOptions | None = None,
) -> SuggestResult:
    """FTS typeahead via Direct ZeusPort. Empty query → empty hits (no agent)."""
    opts = options or SuggestOptions()
    q = (query or "").strip()
    if len(q) < opts.min_query_len:
        return SuggestResult(
            query=q,
            hits=(),
            count=0,
            source="none",
            sources=(),
        )

    body = {
        "entity_type": opts.entity_type,
        "strategy": opts.strategy or "fts",
        "query_text": q,
        "limit": opts.limit,
        "timeout_ms": opts.fts_timeout_ms,
    }
    hop = await zeus.call_verb(
        VerbRequest(
            verb="search",
            body=body,
            target=target,
            mode_header=opts.mode_header,
            headers=correlation_headers(trace_class=TRACE_CLASS_DIRECT_INTERACTIVE),
        )
    )
    if not hop.ok:
        return SuggestResult(
            query=q,
            hits=(),
            count=0,
            source="error",
            sources=(),
            fts_req_id=hop.req_id or "",
            error=hop.error or f"status {hop.status_code}",
        )

    fts_hits = _hits_from_fts(hop.body, source="fts")
    merged = merge_hits(fts_hits, limit=opts.limit)
    sources = ("fts",) if merged else ()
    return SuggestResult(
        query=q,
        hits=tuple(merged),
        count=len(merged),
        source="fts" if merged else "empty",
        sources=sources,
        fts_req_id=hop.req_id or "",
        req_ids=(hop.req_id,) if hop.req_id else (),
        trace_class=TRACE_CLASS_DIRECT_INTERACTIVE,
    )
