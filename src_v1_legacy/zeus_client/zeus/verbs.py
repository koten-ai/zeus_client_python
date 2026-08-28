"""Direct V2 verb runners (no LLM).

Public helpers follow ``run_<zeus_verb>``. Zeus path routing stays in
:func:`zeus_client.zeus.dispatch.dispatch_zeus_v2_verb`.

**Not exposed here:** ``pipeline`` — multi-step DAGs belong in
:func:`zeus_client.agent.loop.run_agent` or low-level
:func:`dispatch_zeus_v2_verb`. Callers that need a pipeline must opt into
that path explicitly.

**search:** product typeahead is :func:`zeus_client.zeus.suggest.run_search`.
Raw ``POST …/search`` bodies use :func:`run_verb` with ``verb="search"``.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from zeus_client.constants import V2_DOCS_VERB_ORDER
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.dispatch import dispatch_zeus_v2_verb

# Canonical V2 verbs minus pipeline (intentional).
EXPOSED_V2_VERBS: tuple[str, ...] = tuple(
    v for v in V2_DOCS_VERB_ORDER if v != "pipeline"
)
EXPOSED_V2_VERB_SET = frozenset(EXPOSED_V2_VERBS)

# Verbs that do not need bucket/scope/collection on the wire (still accepted).
_BARE_VERBS = frozenset({"explain", "return"})


@dataclass(frozen=True)
class VerbResult:
    """Outcome of one direct V2 verb POST."""

    verb: str
    status: int
    text: str
    url: str
    req_id: str = ""
    body: Any = None
    error: str = ""
    target: str = ""
    zeus_url: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= int(self.status) < 300 and not self.error

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def _rewrite_loopback_host(url: str) -> str:
    import os

    raw = (url or "").rstrip("/")
    if "host.docker.internal" not in raw:
        return raw
    if os.path.exists("/.dockerenv"):
        return raw
    return raw.replace("host.docker.internal", "127.0.0.1")


def _with_mode_header(headers: Mapping[str, str], mode: str) -> dict[str, str]:
    h = dict(headers)
    if mode and "X-Zeus-Mode" not in h and "x-zeus-mode" not in {k.lower() for k in h}:
        h["X-Zeus-Mode"] = mode
    return h


def _parse_body(text: str) -> Any:
    try:
        return json.loads(text or "")
    except (TypeError, ValueError):
        return None


def _target(bucket: str, scope: str, collection: str, verb: str) -> str:
    if verb in _BARE_VERBS:
        return verb
    if verb in {"describe", "analyze"}:
        return f"{bucket}/{scope}/{verb}"
    return f"{bucket}/{scope}/{collection}/{verb}"


async def _resolve_headers(
    *,
    zeus_url: str,
    bucket: str,
    scope: str,
    zeus_headers: Mapping[str, str] | None,
    zcfg: Mapping[str, Any] | None,
    mode_header: str,
) -> tuple[dict[str, str] | None, str]:
    if zeus_headers is not None:
        return _with_mode_header(zeus_headers, mode_header), ""
    if zcfg is not None:
        try:
            headers, _note = await resolve_zeus_auth(
                zeus_url, dict(zcfg), bucket or None, scope or None
            )
        except RuntimeError as e:
            return None, str(e)
        return _with_mode_header(headers, mode_header), ""
    return None, "zeus_headers or zcfg required"


async def run_verb(
    verb: str,
    args: Mapping[str, Any] | None = None,
    *,
    zeus_url: str,
    bucket: str = "",
    scope: str = "",
    collection: str = "_default",
    zeus_headers: Mapping[str, str] | None = None,
    zcfg: Mapping[str, Any] | None = None,
    corr_headers: Mapping[str, str] | None = None,
    mode_header: str = "analytics",
    rewind: bool | None = None,
) -> VerbResult:
    """POST one Zeus V2 verb (no LLM).

    ``verb`` must be in :data:`EXPOSED_V2_VERBS`. ``pipeline`` is rejected.
    For typeahead product search prefer :func:`run_search` in ``zeus.suggest``;
    pass ``verb="search"`` here for a raw search body.
    """
    name = (verb or "").strip()
    zeus_url = _rewrite_loopback_host((zeus_url or "").rstrip("/"))
    target = _target(bucket, scope, collection, name)
    payload = dict(args or {})

    if not name:
        return VerbResult(
            verb=name,
            status=0,
            text="",
            url="",
            error="verb required",
            target=target,
            zeus_url=zeus_url,
        )
    if name == "pipeline":
        return VerbResult(
            verb=name,
            status=0,
            text="",
            url="",
            error=(
                "pipeline is not exposed via run_verb; "
                "use run_agent or dispatch_zeus_v2_verb"
            ),
            target=target,
            zeus_url=zeus_url,
        )
    if name not in EXPOSED_V2_VERB_SET:
        return VerbResult(
            verb=name,
            status=0,
            text="",
            url="",
            error=f"unknown or unexposed verb: {name}",
            target=target,
            zeus_url=zeus_url,
        )
    if not zeus_url:
        return VerbResult(
            verb=name,
            status=0,
            text="",
            url="",
            error="no Zeus URL",
            target=target,
            zeus_url=zeus_url,
        )
    if name not in _BARE_VERBS and (not bucket or not scope):
        return VerbResult(
            verb=name,
            status=0,
            text="",
            url="",
            error="bucket and scope required",
            target=target,
            zeus_url=zeus_url,
        )

    headers, err = await _resolve_headers(
        zeus_url=zeus_url,
        bucket=bucket,
        scope=scope,
        zeus_headers=zeus_headers,
        zcfg=zcfg,
        mode_header=mode_header,
    )
    if headers is None:
        return VerbResult(
            verb=name,
            status=0,
            text="",
            url="",
            error=err or "auth failed",
            target=target,
            zeus_url=zeus_url,
        )

    from zeus_client.agent.settings import effective_rewind

    flag = bool(rewind) if rewind is not None else effective_rewind(None, zcfg)
    status, text, url, req_id = await dispatch_zeus_v2_verb(
        zeus_url,
        bucket,
        scope,
        collection,
        name,
        payload,
        headers,
        corr_headers=dict(corr_headers) if corr_headers else None,
        rewind=flag,
    )
    body = _parse_body(text)
    error = ""
    if status == 0 and isinstance(body, dict) and body.get("error"):
        error = str(body.get("message") or body.get("error") or "dispatch_failed")
    elif status >= 400:
        error = f"zeus status {status}"
    return VerbResult(
        verb=name,
        status=int(status or 0),
        text=text or "",
        url=url or "",
        req_id=req_id or "",
        body=body,
        error=error,
        target=target,
        zeus_url=zeus_url,
    )


async def run_verb_from_config(
    verb: str,
    args: Mapping[str, Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
    *,
    sample: str | None = None,
    corr_headers: Mapping[str, str] | None = None,
    mode_header: str = "analytics",
    rewind: bool | None = None,
) -> VerbResult:
    """Resolve sample triple + zeus auth from client config.json, then :func:`run_verb`."""
    from zeus_client.config import resolve_zeus_config

    cfg = dict(cfg or {})
    zcfg = resolve_zeus_config(cfg)
    zeus_url = _rewrite_loopback_host(str(zcfg.get("url") or "").rstrip("/"))
    sample_name = sample or str(cfg.get("default_sample") or "")
    triple = (cfg.get("samples") or {}).get(sample_name) or {}
    if not triple and isinstance(cfg.get("samples"), dict) and cfg["samples"]:
        triple = next(iter(cfg["samples"].values()))
    bucket = str(triple.get("bucket") or sample_name or "")
    scope = str(triple.get("scope") or "_default")
    collection = str(triple.get("collection") or "_default")
    return await run_verb(
        verb,
        args,
        zeus_url=zeus_url,
        bucket=bucket,
        scope=scope,
        collection=collection,
        zcfg=zcfg,
        corr_headers=corr_headers,
        mode_header=mode_header,
        rewind=rewind,
    )


def _make_run_verb(verb_name: str):
    async def _runner(
        args: Mapping[str, Any] | None = None,
        *,
        zeus_url: str,
        bucket: str = "",
        scope: str = "",
        collection: str = "_default",
        zeus_headers: Mapping[str, str] | None = None,
        zcfg: Mapping[str, Any] | None = None,
        corr_headers: Mapping[str, str] | None = None,
        mode_header: str = "analytics",
        rewind: bool | None = None,
    ) -> VerbResult:
        return await run_verb(
            verb_name,
            args,
            zeus_url=zeus_url,
            bucket=bucket,
            scope=scope,
            collection=collection,
            zeus_headers=zeus_headers,
            zcfg=zcfg,
            corr_headers=corr_headers,
            mode_header=mode_header,
            rewind=rewind,
        )

    _runner.__name__ = f"run_{verb_name}"
    _runner.__qualname__ = f"run_{verb_name}"
    _runner.__doc__ = (
        f"POST V2 ``{verb_name}`` (no LLM). See :func:`run_verb`.\n\n"
        f"Not for ``pipeline`` — rejected at :func:`run_verb`."
    )
    return _runner


# Per-verb entrypoints (search product typeahead is zeus.suggest.run_search).
run_describe = _make_run_verb("describe")
run_explain = _make_run_verb("explain")
run_get = _make_run_verb("get")
run_find = _make_run_verb("find")
run_set = _make_run_verb("set")
run_order = _make_run_verb("order")
run_enrich = _make_run_verb("enrich")
run_project = _make_run_verb("project")
run_traverse = _make_run_verb("traverse")
run_analyze = _make_run_verb("analyze")
run_return = _make_run_verb("return")

# Raw search body (typeahead remains zeus.suggest.run_search).
run_search_verb = _make_run_verb("search")

RUN_VERB_HELPERS: dict[str, Any] = {
    "describe": run_describe,
    "explain": run_explain,
    "get": run_get,
    "find": run_find,
    "set": run_set,
    "order": run_order,
    "enrich": run_enrich,
    "project": run_project,
    "traverse": run_traverse,
    "analyze": run_analyze,
    "return": run_return,
    "search": run_search_verb,
}

__all__ = [
    "EXPOSED_V2_VERBS",
    "EXPOSED_V2_VERB_SET",
    "RUN_VERB_HELPERS",
    "VerbResult",
    "run_verb",
    "run_verb_from_config",
    "run_describe",
    "run_explain",
    "run_get",
    "run_find",
    "run_set",
    "run_order",
    "run_enrich",
    "run_project",
    "run_traverse",
    "run_analyze",
    "run_return",
    "run_search_verb",
]
