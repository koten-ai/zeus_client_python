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


@pytest.mark.asyncio
async def test_pat_mints_session_then_find_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    """Valid PAT mints, then one V2 verb uses the session. dev_no_auth stays off."""
    from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort
    from zeus_client.ports import VerbRequest

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "dev_no_auth" not in str(request.url)
        if request.url.path == "/v1/lab/security/auth/session":
            assert request.headers["Authorization"] == "Bearer zeus_pat_good"
            return httpx.Response(
                200,
                json={"session_id": "sess_pat_ok_123", "expires_in": 1800},
            )
        if request.url.path == "/v2/lab/security/items/find":
            assert request.headers.get("X-Zeus-Session") == "sess_pat_ok_123"
            assert "authorization" not in {k.lower() for k in request.headers}
            return httpx.Response(
                200,
                json={"result": {"node_ids": ["n1"]}},
                headers={"X-Zeus-Req-Id": "req-pat-1"},
            )
        return httpx.Response(404, text=request.url.path)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    secrets = EnvSecretStore(environ={"ZEUS_PAT": "zeus_pat_good"})
    endpoint = ZeusEndpointConfig(
        url="http://zeus.example",
        auth_mode="pat",
        token_env="ZEUS_PAT",
    )
    port = HttpxZeusPort(endpoint=endpoint, secrets=secrets, client=http)
    port._auth.client = http
    port._auth._owns_client = False
    caplog.set_level(logging.DEBUG)
    try:
        result = await port.call_verb(
            VerbRequest(
                verb="find",
                body={"entity_type": "Item"},
                target=DataTarget(bucket="lab", scope="security", collection="items"),
            )
        )
    finally:
        await http.aclose()
    assert result.ok
    assert result.status_code == 200
    assert [r.url.path for r in seen] == [
        "/v1/lab/security/auth/session",
        "/v2/lab/security/items/find",
    ]
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "zeus_pat_good" not in blob


@pytest.mark.asyncio
async def test_pat_revoked_returns_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/lab/security/auth/session"
        return httpx.Response(401, json={"error": "unauthenticated"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = ZeusAuthResolver(
        endpoint=ZeusEndpointConfig(
            url="http://zeus.example",
            auth_mode="pat",
            token_env="ZEUS_PAT",
        ),
        secrets=EnvSecretStore(environ={"ZEUS_PAT": "zeus_pat_revoked"}),
        client=http,
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(DataTarget(bucket="lab", scope="security"))
    assert ei.value.code == ErrorCode.AUTH_FAILED
    assert "401" in ei.value.public_message
    await http.aclose()


@pytest.mark.asyncio
async def test_pat_rejects_non_pat_bearer_without_calling_zeus() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"must not send non-PAT bearer: {request.url}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resolver = ZeusAuthResolver(
        endpoint=ZeusEndpointConfig(url="http://zeus.example", auth_mode="pat"),
        secrets=EnvSecretStore(environ={"ZEUS_PAT": "eyJhbGciOiJub25lIn0.e30.sig"}),
        client=http,
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(DataTarget(bucket="lab", scope="security"))
    assert "zeus_pat_" in ei.value.public_message
    await http.aclose()
