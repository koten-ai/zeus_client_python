"""Zeus HTTP verb adapter — httpx POSTs with journaled hops."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from zeus_client.adapters.zeus_http.auth import ZeusAuthResolver
from zeus_client.adapters.zeus_http.headers import (
    apply_mode_header,
    merge_headers,
    product_stamp_headers,
)
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.errors import ErrorCode, ZeusToolError, ZeusTransportError
from zeus_client.domain.journal.events import EVENT_ZEUS_HOP, JournalEvent
from zeus_client.domain.journal.journal import InMemoryJournal
from zeus_client.ports import AuthContext, VerbHopResult, VerbRequest
from zeus_client.ports.secrets import SecretStorePort
from zeus_client.security.redact import default_redactor

__all__ = [
    "EXPOSED_V2_VERBS",
    "EXPOSED_V2_VERB_SET",
    "V2_BARE_VERBS",
    "V2_SCOPE_VERBS",
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

        auth = await self.resolve_auth(req.target)
        url = verb_url(self.endpoint.url, req.target, verb)
        headers = merge_headers(
            auth.headers,
            product_stamp_headers(),
            {"Content-Type": "application/json", "Accept": "application/json"},
            req.headers,
        )
        headers = apply_mode_header(headers, req.mode_header)
        if req.target.bucket and req.target.scope and verb not in V2_BARE_VERBS:
            headers.setdefault("X-Zeus-Scope", f"{req.target.bucket}/{req.target.scope}")

        client = await self._ensure_client()
        req_id: str | None = None
        status = 0
        body: dict[str, Any] = {}
        err: str | None = None
        try:
            resp = await client.post(url, headers=headers, json=dict(req.body))
            status = int(resp.status_code)
            req_id = resp.headers.get("X-Zeus-Req-Id") or resp.headers.get("x-zeus-req-id")
            if not req_id:
                # Capture still; pre-mint only if server omitted (oracle: prefer server).
                req_id = None
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
            self._journal_hop(
                verb=verb,
                url=url,
                status=status,
                req_id=req_id,
                ok=False,
                error=err,
                headers=headers,
            )
            raise ZeusTransportError(
                code=ErrorCode.ZEUS_TRANSPORT,
                component="adapters.zeus_http.verbs",
                public_message="zeus HTTP transport error",
                details={"verb": verb, "url": url},
            ) from exc

        ok = 200 <= status < 300 and not err
        self._journal_hop(
            verb=verb,
            url=url,
            status=status,
            req_id=req_id,
            ok=ok,
            error=err,
            headers=headers,
        )
        return VerbHopResult(
            ok=ok,
            status_code=status,
            req_id=req_id,
            body=body,
            error=err,
        )

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
    ) -> None:
        if self.journal is None:
            return
        red_headers = self._redactor.headers(headers)
        self.journal.append(
            JournalEvent(
                event_id=f"evt_{uuid.uuid4().hex[:16]}",
                ts_ms=int(__import__("time").time() * 1000),
                type=EVENT_ZEUS_HOP,
                component="adapters.zeus_http.verbs",
                turn_id=self.turn_id or "turn_unknown",
                span_id=None,
                parent_span_id=None,
                data={
                    "verb": verb,
                    "url": url,
                    "status": status,
                    "req_id": req_id,
                    "ok": ok,
                    "error": error,
                    "headers": red_headers,
                },
            )
        )
