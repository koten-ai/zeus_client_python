"""Zeus durable session HTTP adapter — create / rehydrate / turn / trace.

No process-global HTTP client. Server mints ``session_id``; client never invents one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import httpx

from zeus_client_v2.adapters.zeus_http.auth import ZeusAuthResolver
from zeus_client_v2.adapters.zeus_http.headers import (
    apply_mode_header,
    merge_headers,
    product_stamp_headers,
)
from zeus_client_v2.config.models import DataTarget, ZeusEndpointConfig
from zeus_client_v2.ports.secrets import SecretStorePort

__all__ = ["SessionHttpResult", "HttpxSessionClient"]


@dataclass(frozen=True, slots=True)
class SessionHttpResult:
    ok: bool
    status_code: int
    body: Mapping[str, Any] | str
    url: str
    req_id: str | None = None
    error: str | None = None


@dataclass
class HttpxSessionClient:
    """HTTP surface for ``/v2/session*`` APIs."""

    endpoint: ZeusEndpointConfig
    secrets: SecretStorePort
    client: httpx.AsyncClient | None = None
    _owns_client: bool = False
    _auth: ZeusAuthResolver = field(init=False)
    timeout_s: float | None = None

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
        mode: str = "",
        extra: Mapping[str, str] | None = None,
        target: DataTarget | None = None,
    ) -> dict[str, str]:
        auth = await self._auth.resolve(target or DataTarget())
        h = merge_headers(
            auth.headers,
            product_stamp_headers(),
            {"Content-Type": "application/json", "Accept": "application/json"},
            extra,
        )
        return apply_mode_header(h, mode)

    async def create(
        self,
        *,
        contract_id: str,
        contract_hash: str,
        chat_request: Mapping[str, Any],
        conversation: Sequence[Mapping[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
        mode: str = "",
        target: DataTarget | None = None,
    ) -> SessionHttpResult:
        url = f"{self._base()}/v2/session"
        payload = {
            "contract_id": contract_id or "",
            "contract_hash": contract_hash or "",
            "chat_request": dict(chat_request or {}),
            "conversation": list(conversation or []),
        }
        h = await self._headers(mode=mode, extra=headers, target=target)
        return await self._post(url, h, payload, ok_codes=(200, 201))

    async def rehydrate(
        self,
        session_id: str,
        *,
        rounds: int = 6,
        headers: Mapping[str, str] | None = None,
        mode: str = "",
        target: DataTarget | None = None,
    ) -> dict[str, Any] | None:
        sid = (session_id or "").strip()
        if not sid:
            return None
        url = f"{self._base()}/v2/session/{sid}"
        h = await self._headers(mode=mode, extra=headers, target=target)
        client = await self._ensure_client()
        try:
            r = await client.get(url, headers=h, params={"rounds": int(rounds)})
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def continue_turn(
        self,
        *,
        session_id: str,
        client_round: int,
        chat_request: Mapping[str, Any],
        new_turns: Sequence[Mapping[str, Any]],
        headers: Mapping[str, str] | None = None,
        mode: str = "",
        target: DataTarget | None = None,
    ) -> SessionHttpResult:
        sid = (session_id or "").strip()
        if not sid:
            return SessionHttpResult(
                ok=False,
                status_code=0,
                body="no session_id",
                url="",
                error="no session_id",
            )
        url = f"{self._base()}/v2/session/{sid}/turn"
        payload = {
            "round": int(client_round),
            "chat_request": dict(chat_request or {}),
            "new_turns": list(new_turns or []),
        }
        h = await self._headers(mode=mode, extra=headers, target=target)
        return await self._post(url, h, payload, ok_codes=(200,))

    async def post_trace(
        self,
        *,
        session_id: str,
        client_round: int,
        req_id: str,
        contract_id: str,
        contract_hash: str,
        chat_request: Mapping[str, Any],
        turns: Sequence[Mapping[str, Any]] | None = None,
        zeus_response: Mapping[str, Any] | None = None,
        outcome: str = "ok",
        headers: Mapping[str, str] | None = None,
        mode: str = "",
        target: DataTarget | None = None,
    ) -> SessionHttpResult:
        sid = (session_id or "").strip()
        if not sid or int(client_round) <= 0:
            return SessionHttpResult(
                ok=False,
                status_code=0,
                body="bad trace params",
                url="",
                error="bad trace params",
            )
        url = f"{self._base()}/v2/session/trace"
        payload = {
            "session_id": sid,
            "round": int(client_round),
            "req_id": req_id or "",
            "contract_id": contract_id or "",
            "contract_hash": contract_hash or "",
            "chat_request": dict(chat_request or {}),
            "turns": list(turns or []),
            "zeus_response": dict(zeus_response or {}),
            "outcome": outcome or "ok",
        }
        h = await self._headers(mode=mode, extra=headers, target=target)
        return await self._post(url, h, payload, ok_codes=(200, 201))

    async def _post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        ok_codes: tuple[int, ...],
    ) -> SessionHttpResult:
        client = await self._ensure_client()
        try:
            r = await client.post(url, headers=dict(headers), json=dict(payload))
            req_id = r.headers.get("X-Zeus-Req-Id") or r.headers.get("x-zeus-req-id")
            status = int(r.status_code)
            if status in ok_codes:
                try:
                    body: Any = r.json()
                except Exception:
                    body = {"raw": r.text}
                if not isinstance(body, dict):
                    body = {"raw": body}
                body = dict(body)
                body["_req_id"] = req_id or ""
                return SessionHttpResult(
                    ok=True,
                    status_code=status,
                    body=body,
                    url=url,
                    req_id=req_id,
                )
            return SessionHttpResult(
                ok=False,
                status_code=status,
                body=(r.text or "")[:2000],
                url=url,
                req_id=req_id,
                error=f"HTTP {status}",
            )
        except httpx.HTTPError as e:
            return SessionHttpResult(
                ok=False,
                status_code=0,
                body=str(e),
                url=url,
                error=str(e),
            )
