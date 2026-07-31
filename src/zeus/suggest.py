"""Fast-tier typeahead via Zeus verbs (no LLM).

Naming: public helpers are ``run_<primary_verb>``. This path's primary
wire verb is ``search`` (FTS), so the entrypoints are ``run_search`` /
``run_search_from_config`` — not product nicknames like ``fast_suggest``.

Google-like dropdown path for apps that sit on Zeus V2:

1. ``search`` strategy ``fts`` → ranked ``src_keys`` / items (cheap token recall)
2. Optional N1QL ``USE KEYS`` hydrate for source-doc card fields
3. Optional exact ``find`` → ``project`` for full name / city equality

This is **not** the agent loop. Callers debounce in the UI and use
``run_agent`` only for full natural-language submit.

See demo_yelp ``local_guide.suggest`` for the productized BFF twin.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, MutableMapping, Sequence
from urllib.parse import urlparse

import httpx

from zeus_client.http_client import client
from zeus_client.logging_setup import logger
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.dispatch import dispatch_zeus_call

DEFAULT_LIMIT = 8
MIN_QUERY_LEN = 2
DEFAULT_FTS_TIMEOUT_MS = 2000
DEFAULT_N1QL_TIMEOUT_S = 3.0
DEFAULT_ENTITY_TYPE = "Business"
DEFAULT_PROJECT_FIELDS: tuple[str, ...] = (
    "name",
    "city",
    "state",
    "stars",
    "review_count",
    "categories",
    "address",
    "latitude",
    "longitude",
)

_CITY_RE = re.compile(
    r"\b(?:in|near|around)\s+([A-Za-z][A-Za-z .'-]{1,40})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SuggestHit:
    """One dropdown / typeahead row."""

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
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep UI payloads small; raw is optional debug.
        if not d.get("raw"):
            d.pop("raw", None)
        return d


@dataclass(frozen=True)
class SuggestResult:
    query: str
    hits: tuple[SuggestHit, ...]
    count: int
    source: str
    sources: tuple[str, ...]
    target: str = ""
    zeus_url: str = ""
    fts_req_id: str = ""
    error: str = ""
    fast_tier: bool = True
    ai_process_result: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [h.to_dict() for h in self.hits],
            "hits": [h.to_dict() for h in self.hits],
            "count": self.count,
            "source": self.source,
            "sources": list(self.sources),
            "target": self.target,
            "zeus_url": self.zeus_url,
            "fts_req_id": self.fts_req_id,
            "error": self.error or None,
            "fast_tier": self.fast_tier,
            "ai_process_result": self.ai_process_result,
        }


@dataclass(frozen=True)
class CouchbaseQueryConfig:
    """Optional direct Query-service hydrate (not Zeus public N1QL)."""

    query_url: str
    username: str = "Administrator"
    password: str = "password"

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        zeus_url: str = "",
        allow_host_default: bool = True,
    ) -> CouchbaseQueryConfig | None:
        """Build query config from mapping/env; optionally derive host:8093 from Zeus URL."""
        m = dict(raw or {})
        query_url = (
            (os.environ.get("COUCHBASE_QUERY_URL") or "").strip()
            or str(m.get("query_url") or "").strip()
        )
        if not query_url and allow_host_default and zeus_url:
            parsed = urlparse(zeus_url.rstrip("/"))
            host = parsed.hostname or "127.0.0.1"
            query_url = f"http://{host}:8093"
        if not query_url:
            return None
        query_url = _rewrite_loopback_host(query_url.rstrip("/"))
        user = (
            (os.environ.get("COUCHBASE_USERNAME") or "").strip()
            or str(m.get("username") or "Administrator").strip()
        )
        password = (
            os.environ.get("COUCHBASE_PASSWORD")
            if os.environ.get("COUCHBASE_PASSWORD") is not None
            else m.get("password", "password")
        )
        return cls(query_url=query_url, username=user, password=str(password))


@dataclass(frozen=True)
class SuggestOptions:
    """Knobs for :func:`run_search` (fast-tier typeahead)."""

    entity_type: str = DEFAULT_ENTITY_TYPE
    limit: int = DEFAULT_LIMIT
    min_query_len: int = MIN_QUERY_LEN
    fts_timeout_ms: int = DEFAULT_FTS_TIMEOUT_MS
    n1ql_timeout_s: float = DEFAULT_N1QL_TIMEOUT_S
    project_fields: tuple[str, ...] = DEFAULT_PROJECT_FIELDS
    # FTS always attempted when q is long enough.
    use_fts: bool = True
    # Exact equality find→project on full query as name.
    use_find_name: bool = True
    # find→project when query looks like / ends with a city.
    use_find_city: bool = True
    # Direct CB hydrate of FTS src_keys (recommended for card fields).
    use_n1ql_hydrate: bool = True
    include_raw: bool = False
    mode_header: str = "analytics"
    api_version: str = "v2"


def _rewrite_loopback_host(url: str) -> str:
    raw = (url or "").rstrip("/")
    if "host.docker.internal" not in raw:
        return raw
    if os.path.exists("/.dockerenv"):
        return raw
    return raw.replace("host.docker.internal", "127.0.0.1")


def _parse_json_body(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _result_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, dict):
        items = result.get("items")
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
    return []


def src_keys_from_fts_payload(payload: Mapping[str, Any]) -> list[str]:
    """Extract ordered source doc keys from a V2 ``search`` / text_search envelope."""
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    keys = result.get("src_keys") if isinstance(result, dict) else None
    out: list[str] = []
    if isinstance(keys, list):
        for k in keys:
            s = str(k or "").strip()
            if s:
                out.append(s)
    if out:
        return _dedupe_preserve(out)
    for item in _result_items(payload):
        node = item.get("node") if isinstance(item.get("node"), dict) else item
        if not isinstance(node, dict):
            continue
        for key in ("doc_key", "source", "id", "key"):
            s = str(node.get(key) or "").strip()
            if s:
                out.append(s)
                break
    return _dedupe_preserve(out)


def scores_by_src_key(payload: Mapping[str, Any]) -> dict[str, float]:
    """Map src_key / doc_key → FTS score when present on items."""
    out: dict[str, float] = {}
    for item in _result_items(payload):
        score_raw = item.get("score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        node = item.get("node") if isinstance(item.get("node"), dict) else item
        if not isinstance(node, dict):
            continue
        for key in ("doc_key", "source", "id", "key"):
            s = str(node.get(key) or "").strip()
            if s and score is not None and s not in out:
                out[s] = score
                break
    return out


def rows_from_project_or_pipeline(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize project / terminating pipeline row shapes."""
    if isinstance(payload.get("rows"), dict):
        inner = payload["rows"].get("rows")
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
    if isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("rows"), list):
        return [r for r in result["rows"] if isinstance(r, dict)]
    # Some envelopes nest under data.<as>
    data = payload.get("data")
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, dict) and isinstance(v.get("rows"), list):
                return [r for r in v["rows"] if isinstance(r, dict)]
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [r for r in v if isinstance(r, dict)]
    return []


def guess_city(query: str) -> str | None:
    q = (query or "").strip()
    m = _CITY_RE.search(q)
    if m:
        return m.group(1).strip(" .,")
    if " " not in q and q[:1].isupper() and q.isalpha() and len(q) >= 4:
        return q
    return None


def _dedupe_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _norm_id(raw: str) -> str:
    s = (raw or "").strip().lower()
    for prefix in ("biz:yelp:", "biz:", "file::"):
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _categories_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        parts = [str(x).strip() for x in v if str(x).strip()]
        return ", ".join(parts)
    return str(v).strip()


def row_to_hit(
    row: Mapping[str, Any],
    *,
    score: float | None = None,
    source: str = "",
    include_raw: bool = False,
) -> SuggestHit | None:
    """Map a hydrate / project row into a :class:`SuggestHit`."""
    if row.get("missing") is True:
        return None
    # Nested node envelope
    node = row.get("node") if isinstance(row.get("node"), dict) else None
    base: Mapping[str, Any] = node if isinstance(node, Mapping) else row

    name = str(
        base.get("name")
        or base.get("title")
        or base.get("business_name")
        or ""
    ).strip()
    doc_id = str(
        base.get("doc_key")
        or base.get("business_id")
        or base.get("id")
        or base.get("source")
        or row.get("doc_key")
        or row.get("business_id")
        or row.get("id")
        or ""
    ).strip()
    if not name and not doc_id:
        return None
    if not name:
        name = doc_id
    city = str(base.get("city") or row.get("city") or "").strip()
    state = str(base.get("state") or row.get("state") or "").strip()
    stars = _as_float(base.get("stars") if "stars" in base else row.get("stars"))
    if stars is None:
        stars = _as_float(base.get("rating") or row.get("rating"))
    review_count = _as_int(
        base.get("review_count") if "review_count" in base else row.get("review_count")
    )
    categories = _categories_str(base.get("categories") or row.get("categories"))
    address = str(base.get("address") or row.get("address") or "").strip()
    loc_bits = [p for p in (city, state) if p]
    star_bit = f"★{stars:g}" if stars is not None else ""
    sub_bits = [b for b in (star_bit, " · ".join(loc_bits) if loc_bits else "", categories) if b]
    subtitle = " · ".join(sub_bits)
    item_score = score
    if item_score is None:
        item_score = _as_float(row.get("score"))
    return SuggestHit(
        id=doc_id or name,
        name=name,
        subtitle=subtitle,
        city=city,
        state=state,
        stars=stars,
        review_count=review_count,
        categories=categories,
        address=address,
        score=item_score,
        source=source,
        raw=dict(row) if include_raw else {},
    )


def merge_hits(
    *groups: Sequence[SuggestHit],
    limit: int,
) -> list[SuggestHit]:
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


async def _dispatch_json(
    zeus_url: str,
    bucket: str,
    scope: str,
    collection: str,
    headers: Mapping[str, str],
    name: str,
    args: dict[str, Any],
    *,
    api_version: str = "v2",
) -> tuple[int, dict[str, Any], str]:
    status, text, _url, req_id = await dispatch_zeus_call(
        api_version,
        zeus_url,
        bucket,
        scope,
        collection,
        name,
        args,
        dict(headers),
    )
    return status, _parse_json_body(text), req_id or ""


async def fts_search_keys(
    zeus_url: str,
    bucket: str,
    scope: str,
    collection: str,
    headers: Mapping[str, str],
    query: str,
    *,
    entity_type: str = DEFAULT_ENTITY_TYPE,
    limit: int = DEFAULT_LIMIT,
    timeout_ms: int = DEFAULT_FTS_TIMEOUT_MS,
    api_version: str = "v2",
) -> tuple[list[str], dict[str, float], dict[str, Any], str]:
    """Run V2 FTS search; return (src_keys, scores, payload, req_id)."""
    status, payload, req_id = await _dispatch_json(
        zeus_url,
        bucket,
        scope,
        collection,
        headers,
        "search",
        {
            "entity_type": entity_type,
            "strategy": "fts",
            "query_text": query,
            "limit": limit,
            "timeout_ms": timeout_ms,
        },
        api_version=api_version,
    )
    if status != 200:
        logger.warning(
            "suggest fts status=%s req=%s body=%s",
            status,
            (req_id or "")[:12],
            str(payload)[:240],
        )
        return [], {}, payload, req_id
    keys = src_keys_from_fts_payload(payload)
    scores = scores_by_src_key(payload)
    return keys, scores, payload, req_id


async def find_project_rows(
    zeus_url: str,
    bucket: str,
    scope: str,
    collection: str,
    headers: Mapping[str, str],
    where: Mapping[str, Any],
    *,
    entity_type: str = DEFAULT_ENTITY_TYPE,
    limit: int = DEFAULT_LIMIT,
    fields: Sequence[str] = DEFAULT_PROJECT_FIELDS,
    api_version: str = "v2",
) -> list[dict[str, Any]]:
    """Exact predicate find → project via V2 pipeline (graph ids, not FTS keys)."""
    status, payload, _rid = await _dispatch_json(
        zeus_url,
        bucket,
        scope,
        collection,
        headers,
        "pipeline",
        {
            "confidence": "med",
            "steps": [
                {
                    "as": "f",
                    "tool": "find",
                    "args": {
                        "entity_type": entity_type,
                        "where": dict(where),
                        "limit": limit,
                    },
                },
                {
                    "as": "rows",
                    "tool": "project",
                    "args": {
                        "ids": "@f.ids",
                        "fields": list(fields),
                    },
                },
            ],
            "return": ["rows"],
        },
        api_version=api_version,
    )
    if status != 200:
        return []
    rows = rows_from_project_or_pipeline(payload)
    return [r for r in rows if not r.get("missing")]


async def n1ql_hydrate_keys(
    cb: CouchbaseQueryConfig,
    bucket: str,
    scope: str,
    collection: str,
    keys: Sequence[str],
    *,
    fields: Sequence[str] = DEFAULT_PROJECT_FIELDS,
    timeout_s: float = DEFAULT_N1QL_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """``USE KEYS`` hydrate — O(keys), preserves caller order when re-sorted."""
    if not keys:
        return []
    # SQL++ identifiers: bucket/scope/collection from operator config only.
    field_sql = ", ".join(f"`{f}`" if not str(f).startswith("`") else str(f) for f in fields)
    # META().id always useful as doc_key.
    if "doc_key" not in fields and "META().id" not in field_sql:
        select_list = f"META().id AS doc_key, {field_sql}" if field_sql else "META().id AS doc_key"
    else:
        select_list = field_sql or "META().id AS doc_key"
    keys_lit = ", ".join(json.dumps(k) for k in keys)
    statement = (
        f"SELECT {select_list} "
        f"FROM `{bucket}`.`{scope}`.`{collection}` "
        f"USE KEYS [{keys_lit}]"
    )
    url = f"{cb.query_url.rstrip('/')}/query/service"
    try:
        # Prefer shared client when initialised; fall back to one-shot for scripts.
        try:
            http = client()
            res = await http.post(
                url,
                data={"statement": statement},
                auth=(cb.username, cb.password),
                timeout=timeout_s,
            )
        except RuntimeError:
            async with httpx.AsyncClient(timeout=timeout_s) as http:
                res = await http.post(
                    url,
                    data={"statement": statement},
                    auth=(cb.username, cb.password),
                )
    except httpx.HTTPError as e:
        logger.warning("suggest n1ql unreachable %s: %s", url, e)
        return []
    if res.status_code != 200:
        logger.warning("suggest n1ql status=%s body=%s", res.status_code, (res.text or "")[:240])
        return []
    try:
        body = res.json()
    except Exception:
        return []
    rows = body.get("results") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        doc_key = str(row.get("doc_key") or "").strip()
        if doc_key:
            row.setdefault("business_id", doc_key)
            row.setdefault("id", doc_key)
        out.append(row)
    return out


def _with_mode_header(headers: Mapping[str, str], mode: str) -> dict[str, str]:
    h = dict(headers)
    if mode and "X-Zeus-Mode" not in h and "x-zeus-mode" not in {k.lower() for k in h}:
        h["X-Zeus-Mode"] = mode
    return h


async def run_search(
    query: str,
    *,
    zeus_url: str,
    bucket: str,
    scope: str,
    collection: str = "_default",
    zeus_headers: Mapping[str, str] | None = None,
    zcfg: Mapping[str, Any] | None = None,
    couchbase: Mapping[str, Any] | CouchbaseQueryConfig | None = None,
    options: SuggestOptions | None = None,
) -> SuggestResult:
    """No-LLM typeahead for ``bucket/scope/collection`` via V2 ``search`` (+ helpers).

    Named ``run_search`` after the primary Zeus verb (``search`` / FTS). This is
    **not** ``run_agent`` — no LLM loop.

    Auth: pass ``zeus_headers`` **or** ``zcfg`` (resolved via
    :func:`resolve_zeus_auth`). Prefer headers when the BFF already minted
    a session.

    Hydrate: when ``options.use_n1ql_hydrate`` and Couchbase query settings
    resolve, FTS ``src_keys`` are turned into card rows via N1QL ``USE KEYS``.
    Without CB access, FTS items are best-effort mapped and name/city
    ``find``→``project`` still run.
    """
    opts = options or SuggestOptions()
    q = (query or "").strip()
    lim = max(1, min(int(opts.limit or DEFAULT_LIMIT), 20))
    target = f"{bucket}/{scope}/{collection}"
    zeus_url = _rewrite_loopback_host((zeus_url or "").rstrip("/"))

    if len(q) < int(opts.min_query_len):
        return SuggestResult(
            query=q,
            hits=(),
            count=0,
            source="none",
            sources=(),
            target=target,
            zeus_url=zeus_url,
        )

    if not zeus_url:
        return SuggestResult(
            query=q,
            hits=(),
            count=0,
            source="error",
            sources=(),
            target=target,
            error="no Zeus URL",
        )

    headers: dict[str, str]
    if zeus_headers is not None:
        headers = _with_mode_header(zeus_headers, opts.mode_header)
    elif zcfg is not None:
        try:
            headers, _note = await resolve_zeus_auth(zeus_url, dict(zcfg), bucket, scope)
        except RuntimeError as e:
            return SuggestResult(
                query=q,
                hits=(),
                count=0,
                source="error",
                sources=(),
                target=target,
                zeus_url=zeus_url,
                error=str(e),
            )
        headers = _with_mode_header(headers, opts.mode_header)
    else:
        return SuggestResult(
            query=q,
            hits=(),
            count=0,
            source="error",
            sources=(),
            target=target,
            zeus_url=zeus_url,
            error="zeus_headers or zcfg required",
        )

    cb_cfg: CouchbaseQueryConfig | None = None
    if opts.use_n1ql_hydrate:
        if isinstance(couchbase, CouchbaseQueryConfig):
            cb_cfg = couchbase
        elif couchbase is not None or (os.environ.get("COUCHBASE_QUERY_URL") or "").strip():
            # Only open a Query-service path when the app opted in (mapping/env).
            # Avoid a surprise 3s timeout to host:8093 on pure-Zeus deploys.
            cb_cfg = CouchbaseQueryConfig.from_mapping(
                couchbase if isinstance(couchbase, Mapping) else None,
                zeus_url=zeus_url,
                allow_host_default=True,
            )
        else:
            cb_cfg = None

    sources: list[str] = []
    fts_req = ""
    fts_hits: list[SuggestHit] = []
    name_hits: list[SuggestHit] = []
    city_hits: list[SuggestHit] = []
    scores: dict[str, float] = {}

    # 1) FTS
    if opts.use_fts:
        try:
            keys, scores, fts_payload, fts_req = await fts_search_keys(
                zeus_url,
                bucket,
                scope,
                collection,
                headers,
                q,
                entity_type=opts.entity_type,
                limit=lim,
                timeout_ms=opts.fts_timeout_ms,
                api_version=opts.api_version,
            )
            if keys or _result_items(fts_payload):
                sources.append("zeus_fts")
            fts_rows: list[dict[str, Any]] = []
            if keys and cb_cfg is not None and opts.use_n1ql_hydrate:
                fts_rows = await n1ql_hydrate_keys(
                    cb_cfg,
                    bucket,
                    scope,
                    collection,
                    keys,
                    fields=opts.project_fields,
                    timeout_s=opts.n1ql_timeout_s,
                )
                if fts_rows:
                    sources.append("n1ql_hydrate")
                    by_key = {
                        str(r.get("doc_key") or r.get("business_id") or r.get("id") or ""): r
                        for r in fts_rows
                    }
                    ordered = [by_key[k] for k in keys if k in by_key]
                    fts_rows = ordered or fts_rows
            if fts_rows:
                for r in fts_rows:
                    kid = str(r.get("doc_key") or r.get("business_id") or r.get("id") or "")
                    hit = row_to_hit(
                        r,
                        score=scores.get(kid),
                        source="zeus_fts+n1ql",
                        include_raw=opts.include_raw,
                    )
                    if hit:
                        fts_hits.append(hit)
            else:
                # Best-effort cards from FTS items (may be thin / id-only).
                for item in _result_items(fts_payload):
                    hit = row_to_hit(
                        item,
                        source="zeus_fts",
                        include_raw=opts.include_raw,
                    )
                    if hit:
                        fts_hits.append(hit)
                # Key-only placeholders if items empty but keys present.
                if not fts_hits and keys:
                    for k in keys:
                        fts_hits.append(
                            SuggestHit(
                                id=k,
                                name=k,
                                score=scores.get(k),
                                source="zeus_fts_keys",
                            )
                        )
        except Exception as e:
            logger.warning("suggest fts path failed: %s", e)

    # 2) Exact name find
    if opts.use_find_name:
        try:
            name_rows = await find_project_rows(
                zeus_url,
                bucket,
                scope,
                collection,
                headers,
                {"name": q},
                entity_type=opts.entity_type,
                limit=lim,
                fields=opts.project_fields,
                api_version=opts.api_version,
            )
            for r in name_rows:
                hit = row_to_hit(r, source="zeus_find_name", include_raw=opts.include_raw)
                if hit:
                    name_hits.append(hit)
            if name_hits:
                sources.append("zeus_find_name")
        except Exception as e:
            logger.warning("suggest find name failed: %s", e)

    # 3) City find
    if opts.use_find_city:
        city = guess_city(q)
        if city:
            try:
                city_rows = await find_project_rows(
                    zeus_url,
                    bucket,
                    scope,
                    collection,
                    headers,
                    {"city": city},
                    entity_type=opts.entity_type,
                    limit=lim,
                    fields=opts.project_fields,
                    api_version=opts.api_version,
                )
                for r in city_rows:
                    hit = row_to_hit(r, source="zeus_find_city", include_raw=opts.include_raw)
                    if hit:
                        city_hits.append(hit)
                if city_hits:
                    sources.append("zeus_find_city")
            except Exception as e:
                logger.warning("suggest find city failed: %s", e)

    hits = merge_hits(fts_hits, name_hits, city_hits, limit=lim)
    source = "+".join(sources) if sources else "empty"
    return SuggestResult(
        query=q,
        hits=tuple(hits),
        count=len(hits),
        source=source,
        sources=tuple(sources),
        target=target,
        zeus_url=zeus_url,
        fts_req_id=fts_req,
    )


async def run_search_from_config(
    query: str,
    cfg: Mapping[str, Any],
    *,
    sample: str | None = None,
    options: SuggestOptions | None = None,
) -> SuggestResult:
    """Convenience: resolve sample triple + zeus/couchbase from client config.json."""
    from zeus_client.config import resolve_zeus_config

    zcfg = resolve_zeus_config(dict(cfg))
    zeus_url = _rewrite_loopback_host(str(zcfg.get("url") or "").rstrip("/"))
    sample_name = sample or str(cfg.get("default_sample") or "")
    triple = (cfg.get("samples") or {}).get(sample_name) or {}
    if not triple and isinstance(cfg.get("samples"), dict) and cfg["samples"]:
        # fall back to first sample
        triple = next(iter(cfg["samples"].values()))
    bucket = str(triple.get("bucket") or sample_name or "")
    scope = str(triple.get("scope") or "_default")
    collection = str(triple.get("collection") or "_default")
    cb = cfg.get("couchbase") if isinstance(cfg.get("couchbase"), dict) else None
    return await run_search(
        query,
        zeus_url=zeus_url,
        bucket=bucket,
        scope=scope,
        collection=collection,
        zcfg=zcfg,
        couchbase=cb,
        options=options,
    )


# Deprecated aliases (≤1 Client release). Prefer run_search / run_search_from_config.
run_fast_suggest = run_search
run_fast_suggest_from_config = run_search_from_config


def apply_suggest_config_defaults(cfg: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Ensure optional ``couchbase`` + yelp sample keys exist (non-destructive)."""
    cfg.setdefault(
        "couchbase",
        {
            "query_url": "",
            "username": "Administrator",
            "password": "password",
        },
    )
    samples = cfg.setdefault("samples", {})
    if isinstance(samples, dict) and "yelp" not in samples and "yelp-data" not in samples:
        samples.setdefault(
            "yelp",
            {
                "bucket": "yelp-data",
                "scope": "_default",
                "collection": "_default",
            },
        )
    return cfg
