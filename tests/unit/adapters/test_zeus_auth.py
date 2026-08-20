"""Per-scope basic mint + no secret logs (CHECKLIST B)."""

from __future__ import annotations

import logging

import httpx
import pytest

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.auth import ZeusAuthResolver
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.errors import AuthError, ErrorCode


@pytest.mark.asyncio
async def test_basic_mints_per_scope_session(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/beer-sample/_default/auth/session"
        assert request.headers.get("Authorization", "").startswith("Basic ")
        return httpx.Response(200, json={"session_id": "sid-abc123456789", "expires_in": 1800})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    secrets = EnvSecretStore(environ={"ZEUS_PASSWORD": "s3cret-password"})
    resolver = ZeusAuthResolver(
        endpoint=ZeusEndpointConfig(
            url="http://zeus.example",
            auth_mode="basic",
            username="admin",
            password_env="ZEUS_PASSWORD",
        ),
        secrets=secrets,
        client=client,
    )
    caplog.set_level(logging.DEBUG)
    ctx = await resolver.resolve(DataTarget(bucket="beer-sample", scope="_default"))
    assert ctx.headers["X-Zeus-Session"] == "sid-abc123456789"
    assert ctx.mode == "basic"
    # cache hit — no second POST
    ctx2 = await resolver.resolve(DataTarget(bucket="beer-sample", scope="_default"))
    assert ctx2.headers["X-Zeus-Session"] == "sid-abc123456789"
    blob = "\n".join(r.message for r in caplog.records)
    assert "s3cret-password" not in blob
    assert "sid-abc123456789" not in blob  # only prefix logged


@pytest.mark.asyncio
async def test_certificate_not_implemented() -> None:
    resolver = ZeusAuthResolver(
        endpoint=ZeusEndpointConfig(auth_mode="certificate", cert_file="/tmp/c.pem")
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(DataTarget())
    assert ei.value.code == ErrorCode.NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_bearer_does_not_log_token(caplog: pytest.LogCaptureFixture) -> None:
    secrets = EnvSecretStore(environ={"ZEUS_BEARER_TOKEN": "tok-super-secret"})
    resolver = ZeusAuthResolver(
        endpoint=ZeusEndpointConfig(auth_mode="bearer", token_env="ZEUS_BEARER_TOKEN"),
        secrets=secrets,
    )
    caplog.set_level(logging.DEBUG)
    ctx = await resolver.resolve(DataTarget())
    assert ctx.headers["Authorization"] == "Bearer tok-super-secret"
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "tok-super-secret" not in blob
