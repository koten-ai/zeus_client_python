"""Zeus HTTP adapter for ``/v2/agent_memory/*`` (ZE-314 / ZF-WISH-001).

Zeus embeds and stores. This client never opens Couchbase or chooses embed dim.
Not the graph tool ``agent_memory.read``.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from zeus_client.adapters.zeus_http.auth import ZeusAuthResolver
from zeus_client.adapters.zeus_http.headers import (
    apply_mode_header,
    merge_headers,
    product_stamp_headers,
    req_id_from_headers,
)
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.ids import new_zeus_req_id
from zeus_client.domain.journal.events import EVENT_ZEUS_HOP, JournalEvent
from zeus_client.domain.journal.journal import InMemoryJournal
from zeus_client.domain.semantic_cache import normalize_block_type
from zeus_client.observability.logging import get_family_logger
from zeus_client.ports.agent_memory import (
    AgentMemoryStatus,
    RecalledBlock,
    RecallResult,
    WriteResult,
)
from zeus_client.ports.secrets import SecretStorePort

__all__ = ["HttpxAgentMemoryClient"]

_RECALL_OK = (200,)
_WRITE_OK = (200, 201)


def _blocks_from_body(body: Mapping[str, Any]) -> tuple[RecalledBlock, ...]:
    raw = body.get("blocks")
    if not isinstance(raw, list):
        return ()
    out: list[RecalledBlock] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        out.append(
            RecalledBlock(
                block_id=str(item.get("block_id") or ""),
                type=normalize_block_type(str(item.get("type") or "")),
                text=str(item.get("text") or ""),
                summary=str(item.get("summary") or ""),
                score=float(item.get("score") or 0.0),
                created_at=str(item.get("created_at") or ""),
            )
        )
    return tuple(out)


@dataclass
class HttpxAgentMemoryClient:
    """HTTP surface for semantic agent cache. Default timeout from Zeus endpoint."""

    endpoint: ZeusEndpointConfig
    secrets: SecretStorePort
    journal: InMemoryJournal | None = None
    turn_id: str = ""
    client: httpx.AsyncClient | None = None
    _owns_client: bool = False
    _auth: ZeusAuthResolver = field(init=False)
    timeout_s: float | None = None
    last_req_id: str | None = None
    pre_mint_req_id: bool = False
    _probe: AgentMemoryStatus | None = field(default=None, init=False, repr=False)
    _probed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._auth = ZeusAuthResolver(endpoint=self.endpoint, secrets=self.secrets)
        if self.timeout_s is None:
            self.timeout_s = self.endpoint.timeout_s

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_s)
            self._owns_client = True
        return self.client

    async def aclose(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None

    def _base(self) -> str:
        return (self.endpoint.url or "").rstrip("/")

    async def _headers(
        self,
        *,
        extra: Mapping[str, str] | None = None,
        target: DataTarget | None = None,
        mode: str = "",
    ) -> dict[str, str]:
        auth = await self._auth.resolve(target or DataTarget())
        h = merge_headers(
            auth.headers,
            product_stamp_headers(),
            {"Content-Type": "application/json", "Accept": "application/json"},
            extra,
        )
        if self.pre_mint_req_id and not any(k.lower() == "x-zeus-req-id" for k in h):
            h["X-Zeus-Req-Id"] = new_zeus_req_id()
        return apply_mode_header(h, mode)

    def _journal(
        self,
        *,
        op: str,
        url: str,
        status: int,
        req_id: str | None,
        ok: bool,
        error: str | None,
        duration_ms: int,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        if self.journal is None:
            return
        data: dict[str, Any] = {
            "verb": f"agent_memory.{op}",
            "url": url,
            "status": status,
            "req_id": req_id,
            "ok": ok,
            "error": error,
            "duration_ms": duration_ms,
            "zeus.url": self._base(),
        }
        if extra:
            data.update(dict(extra))
        self.journal.append(
            JournalEvent(
                event_id=f"evt_{uuid.uuid4().hex[:16]}",
                ts_ms=int(time.time() * 1000),
                type=EVENT_ZEUS_HOP,
                component="adapters.zeus_http.agent_memory",
                turn_id=self.turn_id or "turn_unknown",
                span_id=None,
                parent_span_id=None,
                data=data,
            )
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        timeout: httpx.Timeout | None = None,
        target: DataTarget | None = None,
    ) -> tuple[int, dict[str, Any], str | None, str | None, bool]:
        """Return status, body, req_id, error, timed_out."""
        client = await self._ensure_client()
        h = dict(headers)
        timed_out = False

        async def _once(hdrs: dict[str, str]) -> httpx.Response:
            if method == "GET":
                return await client.get(url, headers=hdrs, timeout=timeout)
            return await client.post(url, headers=hdrs, json=dict(json_body or {}), timeout=timeout)

        try:
            resp = await _once(h)
            if int(resp.status_code) == 401 and (self.endpoint.auth_mode or "") == "basic":
                auth = await self._auth.resolve(target or DataTarget(), force=True)
                h = merge_headers(auth.headers, h)
                resp = await _once(h)
        except httpx.TimeoutException as exc:
            timed_out = True
            return 0, {}, None, str(exc), True
        except httpx.HTTPError as exc:
            return 0, {}, None, str(exc), False

        req_id = req_id_from_headers(resp.headers)
        self.last_req_id = req_id
        status = int(resp.status_code)
        try:
            parsed = resp.json()
            body = parsed if isinstance(parsed, dict) else {"result": parsed}
        except Exception:
            body = {"raw": (resp.text or "")[:2000]}
        err: str | None = None
        if status >= 400:
            err = str(body.get("error_class") or body.get("error") or f"HTTP {status}")
        return status, body, req_id, err, timed_out

    async def status(self) -> AgentMemoryStatus:
        url = f"{self._base()}/v2/agent_memory/status"
        t0 = time.perf_counter()
        log = get_family_logger()
        h = await self._headers()
        status, body, req_id, err, timed_out = await self._request("GET", url, headers=h)
        ms = int((time.perf_counter() - t0) * 1000)
        if timed_out or status == 0 or status == 404 or status >= 400:
            st = AgentMemoryStatus(
                enabled=False,
                status_code=status or 0,
                req_id=req_id,
                error=err or ("timeout" if timed_out else "unavailable"),
                url=url,
            )
            self._probe = st
            self._probed = True
            self._journal(
                op="status",
                url=url,
                status=status,
                req_id=req_id,
                ok=False,
                error=st.error,
                duration_ms=ms,
            )
            log.error(
                "zeus_client.agent_memory.status",
                **{
                    "req_id": req_id,
                    "http.status_code": status,
                    "duration_ms": ms,
                    "result": "timeout" if timed_out else "error",
                    "error.message": st.error,
                },
            )
            return st
        st = AgentMemoryStatus(
            enabled=bool(body.get("enabled")),
            store=bool(body.get("store")),
            embedder=bool(body.get("embedder")),
            recall_mode=str(body.get("recall_mode") or ""),
            feature=str(body.get("feature") or "semantic_agent_cache"),
            status_code=status,
            req_id=req_id,
            url=url,
        )
        self._probe = st
        self._probed = True
        self._journal(
            op="status",
            url=url,
            status=status,
            req_id=req_id,
            ok=True,
            error=None,
            duration_ms=ms,
            extra={"store": st.store, "embedder": st.embedder},
        )
        log.debug(
            "zeus_client.agent_memory.status",
            **{
                "req_id": req_id,
                "enabled": st.enabled,
                "store": st.store,
                "embedder": st.embedder,
                "result": "ok",
            },
        )
        return st

    async def available(self) -> bool:
        if not self._probed:
            await self.status()
        return bool(self._probe and self._probe.available)

    async def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        types: Sequence[str] = (),
        min_score: float = 0.0,
        timeout_ms: int | None = None,
        headers: Mapping[str, str] | None = None,
        user_id: str | None = None,
        memory_session_id: str | None = None,
        bucket: str | None = None,
        scope: str | None = None,
    ) -> RecallResult:
        url = f"{self._base()}/v2/agent_memory/recall"
        payload: dict[str, Any] = {
            "query": query,
            "top_k": int(top_k),
            "min_score": float(min_score),
        }
        if types:
            payload["types"] = [str(t) for t in types]
        if memory_session_id:
            payload["memory_session_id"] = memory_session_id
        if bucket:
            payload["bucket"] = bucket
        if scope:
            payload["scope"] = scope
        if user_id:
            payload["user_id"] = user_id
        budget = 150 if timeout_ms is None else max(1, int(timeout_ms))
        timeout = httpx.Timeout(budget / 1000.0)
        t0 = time.perf_counter()
        log = get_family_logger()
        h = await self._headers(extra=headers)
        status, body, req_id, err, timed_out = await self._request(
            "POST", url, headers=h, json_body=payload, timeout=timeout
        )
        ms = int((time.perf_counter() - t0) * 1000)
        ok = (not timed_out) and status in _RECALL_OK and not err
        blocks = _blocks_from_body(body) if ok else ()
        result = RecallResult(
            ok=ok,
            status_code=status,
            req_id=req_id,
            blocks=blocks,
            embed_model=str(body.get("embed_model") or "") or None,
            mode=str(body.get("mode") or ""),
            latency_ms=int(body.get("latency_ms") or ms),
            error="timeout" if timed_out else err,
            url=url,
            skipped=False,
            skip_reason="timeout" if timed_out else ("" if ok else "error"),
        )
        self._journal(
            op="recall",
            url=url,
            status=status,
            req_id=req_id,
            ok=ok,
            error=result.error,
            duration_ms=ms,
            extra={"block_count": len(blocks), "types": [b.type for b in blocks]},
        )
        attrs = {
            "req_id": req_id,
            "http.status_code": status,
            "duration_ms": ms,
            "block_count": len(blocks),
            "result": "ok" if ok else ("timeout" if timed_out else "error"),
        }
        if ok:
            log.info("zeus_client.agent_memory.recall", **attrs)
        else:
            log.error(
                "zeus_client.agent_memory.recall",
                **{**attrs, "error.message": result.error},
            )
        return result

    async def write_block(
        self,
        text: str,
        *,
        type: str = "conversational",
        summary: str | None = None,
        ttl_seconds: int | None = None,
        headers: Mapping[str, str] | None = None,
        user_id: str | None = None,
        zeus_session_id: str | None = None,
        memory_session_id: str | None = None,
        bucket: str | None = None,
        scope: str | None = None,
    ) -> WriteResult:
        url = f"{self._base()}/v2/agent_memory/blocks"
        payload: dict[str, Any] = {
            "text": text,
            "type": normalize_block_type(type),
        }
        if summary:
            payload["summary"] = summary
        if ttl_seconds is not None:
            payload["ttl_seconds"] = int(ttl_seconds)
        if user_id:
            payload["user_id"] = user_id
        if zeus_session_id:
            payload["zeus_session_id"] = zeus_session_id
        if memory_session_id:
            payload["memory_session_id"] = memory_session_id
        if bucket:
            payload["bucket"] = bucket
        if scope:
            payload["scope"] = scope
        t0 = time.perf_counter()
        log = get_family_logger()
        h = await self._headers(extra=headers)
        status, body, req_id, err, timed_out = await self._request(
            "POST", url, headers=h, json_body=payload
        )
        ms = int((time.perf_counter() - t0) * 1000)
        ok = (not timed_out) and status in _WRITE_OK and not err
        result = WriteResult(
            ok=ok,
            status_code=status,
            req_id=req_id,
            block_id=str(body.get("block_id") or "") or None,
            type=str(body.get("type") or payload["type"]),
            ttl_seconds=int(body.get("ttl_seconds") or payload.get("ttl_seconds") or 0),
            error="timeout" if timed_out else err,
            url=url,
            skipped=False,
            skip_reason="timeout" if timed_out else ("" if ok else "error"),
        )
        self._journal(
            op="write",
            url=url,
            status=status,
            req_id=req_id,
            ok=ok,
            error=result.error,
            duration_ms=ms,
            extra={"type": result.type},
        )
        attrs = {
            "req_id": req_id,
            "http.status_code": status,
            "duration_ms": ms,
            "type": result.type,
            "result": "ok" if ok else ("timeout" if timed_out else "error"),
        }
        if ok:
            log.info("zeus_client.agent_memory.write", **attrs)
        else:
            log.error(
                "zeus_client.agent_memory.write",
                **{**attrs, "error.message": result.error},
            )
        return result
