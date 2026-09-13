"""Zeus HTTP verb adapter — httpx POSTs with journaled hops."""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import quote

import httpx

from zeus_client.adapters.zeus_http.auth import ZeusAuthResolver
from zeus_client.adapters.zeus_http.headers import (
    apply_mode_header,
    merge_headers,
    product_stamp_headers,
    req_id_from_headers,
    rewind_query_params,
    verb_body_without_rewind,
)
from zeus_client.config.models import DataTarget, RetryPolicy, ZeusEndpointConfig
from zeus_client.domain.errors import ErrorCode, ZeusToolError, ZeusTransportError
from zeus_client.domain.ids import new_zeus_req_id
from zeus_client.domain.journal.events import EVENT_ZEUS_HOP, JournalEvent
from zeus_client.domain.journal.journal import InMemoryJournal
from zeus_client.domain.llm_classify import RetryBudget
from zeus_client.observability.logging import get_family_logger
from zeus_client.ports import AuthContext, VerbHopResult, VerbRequest
from zeus_client.ports.secrets import SecretStorePort
from zeus_client.security.redact import default_redactor

__all__ = [
    "EXPOSED_V2_VERBS",
    "EXPOSED_V2_VERB_SET",
    "IDEMPOTENT_READ_VERBS",
    "V2_BARE_VERBS",
    "V2_SCOPE_VERBS",
    "verb_allows_sdk_retry",
    "zeus_hop_retryable",
    "verb_url",
    "HttpxZeusPort",
]

# Canonical V2 verbs minus pipeline (public direct surface).
_V2_ORDER = (
    "describe",
    "explain",
    "get",
    "find",
    "set",
    "order",
    "enrich",
    "project",
    "traverse",
    "pipeline",
    "search",
    "analyze",
    "return",
)
EXPOSED_V2_VERBS: tuple[str, ...] = tuple(v for v in _V2_ORDER if v != "pipeline")
EXPOSED_V2_VERB_SET = frozenset(EXPOSED_V2_VERBS)
V2_BARE_VERBS = frozenset({"explain", "return"})
V2_SCOPE_VERBS = frozenset({"describe", "analyze"})
IDEMPOTENT_READ_VERBS = frozenset(
    {"describe", "explain", "get", "find", "search", "traverse"}
)


def verb_allows_sdk_retry(verb: str) -> bool:
    return (verb or "").strip() in IDEMPOTENT_READ_VERBS


def zeus_hop_retryable(verb: str, *, status: int, transport_err: bool) -> bool:
    """Transport or HTTP 5xx on an idempotent read. Never 4xx/409/429."""
    if not verb_allows_sdk_retry(verb):
        return False
    if transport_err or status == 0:
        return True
    return 500 <= int(status) <= 599


def _backoff_ms(policy: RetryPolicy, attempt: int) -> int:
    base = int(policy.base_delay_ms * (2 ** max(0, attempt)))
    base = min(base, int(policy.max_delay_ms))
    if policy.jitter and base > 0:
        base = int(base * (0.5 + random.random() * 0.5))
    return max(0, base)


def verb_url(base_url: str, target: DataTarget, verb: str) -> str:
    """Build Zeus V2 verb URL (oracle path shapes from V1 dispatch)."""
    root = (base_url or "").rstrip("/")
    name = (verb or "").strip()
    b = quote(str(target.bucket), safe="")
    s = quote(str(target.scope), safe="")
    c = quote(str(target.collection), safe="")
    if name in V2_BARE_VERBS:
        return f"{root}/v2/{name}"
    if name in V2_SCOPE_VERBS:
        return f"{root}/v2/{b}/{s}/{name}"
    return f"{root}/v2/{b}/{s}/{c}/{name}"


@dataclass
class HttpxZeusPort:
    """ZeusPort implementation over a dedicated httpx.AsyncClient (no globals)."""

    endpoint: ZeusEndpointConfig
    secrets: SecretStorePort
    journal: InMemoryJournal | None = None
    turn_id: str = ""
    client: httpx.AsyncClient | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    budget: RetryBudget | None = None
    _owns_client: bool = False
    _auth: ZeusAuthResolver = field(init=False)
    _redactor: Any = field(default_factory=default_redactor)

    def __post_init__(self) -> None:
        self._auth = ZeusAuthResolver(endpoint=self.endpoint, secrets=self.secrets)

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.endpoint.timeout_s)
            self._owns_client = True
        return self.client

    async def aclose(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None

    async def resolve_auth(self, target: DataTarget, *, force: bool = False) -> AuthContext:
        return await self._auth.resolve(target, force=force)

    def _endpoint_for(self, req: VerbRequest) -> ZeusEndpointConfig:
        url = req.base_url or self.endpoint.url
        auth_mode = req.auth_mode if req.auth_mode is not None else self.endpoint.auth_mode
        username = req.username if req.username is not None else self.endpoint.username
        password_env = (
            req.password_env if req.password_env is not None else self.endpoint.password_env
        )
        token_env = req.token_env if req.token_env is not None else self.endpoint.token_env
        if (
            url == self.endpoint.url
            and auth_mode == self.endpoint.auth_mode
            and username == self.endpoint.username
            and password_env == self.endpoint.password_env
            and token_env == self.endpoint.token_env
        ):
            return self.endpoint
        return replace(
            self.endpoint,
            url=url,
            auth_mode=auth_mode,  # type: ignore[arg-type]
            username=username,
            password_env=password_env,
            token_env=token_env,
        )

    async def _auth_for(
        self, req: VerbRequest, target: DataTarget, *, force: bool = False
    ) -> AuthContext:
        endpoint = self._endpoint_for(req)
        if endpoint is self.endpoint:
            return await self._auth.resolve(target, force=force)
        resolver = ZeusAuthResolver(endpoint=endpoint, secrets=self.secrets)
        return await resolver.resolve(target, force=force)

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        verb = (req.verb or "").strip()
        if verb == "pipeline" and not req.allow_pipeline:
            raise ZeusToolError(
                code=ErrorCode.ZEUS_PIPELINE_NOT_ON_DIRECT,
                component="adapters.zeus_http.verbs",
                public_message="zeus pipeline not on direct surface",
            )
        if verb == "pipeline" and req.allow_pipeline:
            pass  # agent-only
        elif verb not in EXPOSED_V2_VERB_SET:
            raise ZeusToolError(
                code=ErrorCode.ZEUS_VERB_NOT_ALLOWED,
                component="adapters.zeus_http.verbs",
                public_message="zeus verb not allow-listed",
                details={"verb": verb},
            )

        auth = await self._auth_for(req, req.target)
        hop_endpoint = self._endpoint_for(req)
        url = verb_url(hop_endpoint.url, req.target, verb)

        def _headers(auth_ctx: Any) -> dict[str, str]:
            out = merge_headers(
                auth_ctx.headers,
                product_stamp_headers(),
                {"Content-Type": "application/json", "Accept": "application/json"},
                req.headers,
            )
            out = apply_mode_header(out, req.mode_header)
            if req.target.bucket and req.target.scope and verb not in V2_BARE_VERBS:
                out.setdefault("X-Zeus-Scope", f"{req.target.bucket}/{req.target.scope}")
            return out

        headers = _headers(auth)
        if req.pre_mint_req_id and not any(k.lower() == "x-zeus-req-id" for k in headers):
            headers["X-Zeus-Req-Id"] = new_zeus_req_id()
        client = await self._ensure_client()
        req_id: str | None = None
        status = 0
        body: dict[str, Any] = {}
        err: str | None = None
        payload = verb_body_without_rewind(req.body)
        params = rewind_query_params(bool(req.rewind))
        scope = (
            f"{req.target.bucket}/{req.target.scope}"
            if req.target.bucket and req.target.scope
            else ""
        )
        zeus_url = (hop_endpoint.url or "").rstrip("/")
        log = get_family_logger()
        budget = self._budget_for_call()
        attempt = 0
        while True:
            t0 = time.perf_counter()
            body = {}
            err = None
            req_id = None
            status = 0
            try:
                resp = await client.post(url, headers=headers, json=payload, params=params or None)
                if int(resp.status_code) == 401 and (hop_endpoint.auth_mode or "") == "basic":
                    auth = await self._auth_for(req, req.target, force=True)
                    headers = _headers(auth)
                    if req.pre_mint_req_id and not any(k.lower() == "x-zeus-req-id" for k in headers):
                        headers["X-Zeus-Req-Id"] = new_zeus_req_id()
                    resp = await client.post(url, headers=headers, json=payload, params=params or None)
                status = int(resp.status_code)
                req_id = req_id_from_headers(resp.headers)
                try:
                    parsed = resp.json()
                    body = parsed if isinstance(parsed, dict) else {"result": parsed}
                except Exception:
                    body = {"raw": (resp.text or "")[:2000]}
                if status >= 400:
                    err = f"zeus HTTP {status}"
            except httpx.HTTPError as exc:
                err = str(exc)
                status = 0
                ms = int((time.perf_counter() - t0) * 1000)
                delay = _backoff_ms(self.retry, attempt)
                if budget.allow(
                    retryable=zeus_hop_retryable(verb, status=0, transport_err=True),
                    delay_ms=delay,
                ):
                    budget.consume(delay)
                    log.info(
                        "zeus_client.zeus.request_retry",
                        verb=verb,
                        attempt=attempt,
                        result="retry",
                        duration_ms=ms,
                    )
                    attempt += 1
                    await self._sleep(delay / 1000)
                    continue
                self._journal_hop(
                    verb=verb,
                    url=url,
                    status=status,
                    req_id=req_id,
                    ok=False,
                    error=err,
                    headers=headers,
                    duration_ms=ms,
                    scope=scope,
                    zeus_url=zeus_url,
                )
                log.error(
                    "zeus_client.zeus.dispatch_failed",
                    **{
                        "req_id": req_id,
                        "verb": verb,
                        "http.status_code": status,
                        "duration_ms": ms,
                        "scope": scope,
                        "zeus.url": zeus_url,
                        "error.type": "transport",
                        "error.message": err,
                        "result": "error",
                    },
                )
                raise ZeusTransportError(
                    code=ErrorCode.ZEUS_TRANSPORT,
                    component="adapters.zeus_http.verbs",
                    public_message="zeus HTTP transport error",
                    details={"verb": verb, "url": url, "req_id": req_id, "scope": scope},
                ) from exc

            ms = int((time.perf_counter() - t0) * 1000)
            if zeus_hop_retryable(verb, status=status, transport_err=False):
                delay = _backoff_ms(self.retry, attempt)
                if budget.allow(retryable=True, delay_ms=delay):
                    budget.consume(delay)
                    log.info(
                        "zeus_client.zeus.request_retry",
                        verb=verb,
                        attempt=attempt,
                        result="retry",
                        **{"http.status_code": status, "duration_ms": ms},
                    )
                    attempt += 1
                    await self._sleep(delay / 1000)
                    continue

            ok = 200 <= status < 300 and not err
            self._journal_hop(
                verb=verb,
                url=url,
                status=status,
                req_id=req_id,
                ok=ok,
                error=err,
                headers=headers,
                duration_ms=ms,
                scope=scope,
                zeus_url=zeus_url,
            )
            hop_attrs = {
                "req_id": req_id,
                "verb": verb,
                "http.status_code": status,
                "duration_ms": ms,
                "scope": scope,
                "zeus.url": zeus_url,
            }
            if ok:
                log.debug("zeus_client.zeus.dispatch", **hop_attrs)
                log.info("zeus_client.zeus.req", **hop_attrs)
            else:
                log.error(
                    "zeus_client.zeus.dispatch_failed",
                    **{
                        **hop_attrs,
                        "error.type": "http_4xx" if 400 <= status < 500 else "http_5xx",
                        "error.message": err,
                        "result": "error",
                    },
                )
            return VerbHopResult(
                ok=ok,
                status_code=status,
                req_id=req_id,
                body=body,
                error=err,
                url=url,
            )

    def _budget_for_call(self) -> RetryBudget:
        if self.budget is not None:
            b = RetryBudget(
                max_attempts=self.budget.max_attempts,
                max_extra_ms=self.budget.max_extra_ms or 30_000,
            )
            return b
        return RetryBudget(max_attempts=int(self.retry.max_attempts))

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        await asyncio.sleep(seconds)

    def _journal_hop(
        self,
        *,
        verb: str,
        url: str,
        status: int,
        req_id: str | None,
        ok: bool,
        error: str | None,
        headers: Mapping[str, str],
        duration_ms: int | None = None,
        scope: str = "",
        zeus_url: str = "",
    ) -> None:
        if self.journal is None:
            return
        red_headers = self._redactor.headers(headers)
        data: dict[str, Any] = {
            "verb": verb,
            "url": url,
            "status": status,
            "req_id": req_id,
            "ok": ok,
            "error": error,
            "headers": red_headers,
            "scope": scope,
            "zeus.url": zeus_url,
        }
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        self.journal.append(
            JournalEvent(
                event_id=f"evt_{uuid.uuid4().hex[:16]}",
                ts_ms=int(time.time() * 1000),
                type=EVENT_ZEUS_HOP,
                component="adapters.zeus_http.verbs",
                turn_id=self.turn_id or "turn_unknown",
                span_id=None,
                parent_span_id=None,
                data=data,
            )
        )
