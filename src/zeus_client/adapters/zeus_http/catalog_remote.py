"""Remote catalog fetch from Zeus (chat_request.json) — no process-global client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from zeus_client.config.models import ZeusEndpointConfig
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.ports.secrets import SecretStorePort

__all__ = ["HttpxCatalogRemote", "CatalogFetchPort"]


class CatalogFetchPort:
    """Protocol-ish duck type for injectability in tests."""

    async def fetch_chat_request(
        self,
        bucket: str,
        scope: str,
        mode: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class HttpxCatalogRemote:
    """GET ``/v1/ai/chat_request.json?scope=&mode=`` via dedicated httpx client."""

    def __init__(
        self,
        endpoint: ZeusEndpointConfig,
        *,
        secrets: SecretStorePort | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.secrets = secrets
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s if timeout_s is not None else endpoint.timeout_s

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_chat_request(
        self,
        bucket: str,
        scope: str,
        mode: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        base = (self.endpoint.url or "").rstrip("/")
        if not base:
            raise CatalogError(
                code=ErrorCode.CATALOG_SYNC_FAILED,
                component="adapters.zeus_http.catalog_remote",
                public_message="zeus url missing for catalog fetch",
            )
        params: dict[str, str] = {"scope": f"{bucket}/{scope}"}
        m = (mode or "default").strip() or "default"
        if m != "default":
            params["mode"] = m
        client = self._ensure_client()
        try:
            r = await client.get(
                f"{base}/v1/ai/chat_request.json",
                params=params,
                headers=dict(headers or {}),
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as e:
            raise CatalogError(
                code=ErrorCode.CATALOG_SYNC_FAILED,
                component="adapters.zeus_http.catalog_remote",
                public_message=f"catalog fetch transport error: {e}",
                details={"bucket": bucket, "scope": scope, "mode": m},
            ) from e
        if r.status_code != 200:
            raise CatalogError(
                code=ErrorCode.CATALOG_SYNC_FAILED,
                component="adapters.zeus_http.catalog_remote",
                public_message=f"chat_request HTTP {r.status_code}: {r.text[:300]}",
                details={
                    "status_code": r.status_code,
                    "bucket": bucket,
                    "scope": scope,
                    "mode": m,
                },
            )
        try:
            data = r.json()
        except Exception as e:
            raise CatalogError(
                code=ErrorCode.CATALOG_PARSE_FAILED,
                component="adapters.zeus_http.catalog_remote",
                public_message="catalog remote JSON parse failed",
            ) from e
        if not isinstance(data, dict):
            raise CatalogError(
                code=ErrorCode.CATALOG_PARSE_FAILED,
                component="adapters.zeus_http.catalog_remote",
                public_message="catalog remote body is not an object",
            )
        return data
