"""ZCP-125 client authn matrix. Every non-n/a cell is one test id.

The ids must match docs/V2/AUTHN_MATRIX.md. A missing id fails this module.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.auth import ZeusAuthResolver
from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort
from zeus_client.config.models import DataTarget, M2MClientConfig, ZeusEndpointConfig
from zeus_client.domain.errors import AuthError
from zeus_client.ports import VerbRequest

ZEUS = "http://zeus.example"
LAB = DataTarget(bucket="lab", scope="security", collection="items")
OTHER = DataTarget(bucket="lab", scope="other", collection="items")

CELL_IDS = (
    "missing_credential_basic",
    "missing_credential_pat",
    "missing_credential_m2m",
    "wrong_secret_basic",
    "wrong_secret_pat",
    "wrong_secret_m2m",
    "good_verb_basic",
    "good_verb_pat",
    "good_verb_m2m",
    "cross_scope_basic",
    "cross_scope_pat",
    "cross_scope_m2m",
    "revoke_pat",
    "lockout_basic",
    "issuer_unset_m2m",
    "wrong_aud_m2m",
    "wrong_iss_m2m",
)


def test_matrix_doc_names_every_cell() -> None:
    text = Path("docs/V2/AUTHN_MATRIX.md").read_text(encoding="utf-8")
    missing = [cell for cell in CELL_IDS if cell not in text]
    assert missing == []


def _m2m(**kwargs: str) -> M2MClientConfig:
    base = dict(
        issuer="https://idp.example/",
        audience="https://zeus.example",
        client_id="zeus-nightly",
        client_secret_env="ZEUS_M2M_CLIENT_SECRET",
        token_url="http://idp.example/token",
        scope="zeus.read zeus.traverse",
    )
    base.update(kwargs)
    return M2MClientConfig(**base)


def _endpoint(mode: str, *, issuer: str = "https://idp.example/") -> ZeusEndpointConfig:
    if mode == "basic":
        return ZeusEndpointConfig(
            url=ZEUS,
            auth_mode="basic",
            username="svc",
            password_env="ZEUS_PASSWORD",
        )
    if mode == "pat":
        return ZeusEndpointConfig(url=ZEUS, auth_mode="pat", token_env="ZEUS_PAT")
    return ZeusEndpointConfig(url=ZEUS, auth_mode="m2m", m2m=_m2m(issuer=issuer))


def _secrets(mode: str, *, value: str | None) -> EnvSecretStore:
    if value is None:
        return EnvSecretStore(environ={})
    if mode == "basic":
        return EnvSecretStore(environ={"ZEUS_PASSWORD": value})
    if mode == "pat":
        return EnvSecretStore(environ={"ZEUS_PAT": value})
    return EnvSecretStore(environ={"ZEUS_M2M_CLIENT_SECRET": value})


def _bind(
    endpoint: ZeusEndpointConfig, secrets: EnvSecretStore, handler
) -> tuple[HttpxZeusPort, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port = HttpxZeusPort(endpoint=endpoint, secrets=secrets, client=http)
    port._auth.client = http
    port._auth._owns_client = False
    return port, http


def _scope_of(path: str) -> str:
    parts = path.split("/")
    return f"{parts[2]}/{parts[3]}"


async def _verb(port: HttpxZeusPort, target: DataTarget):
    return await port.call_verb(
        VerbRequest(verb="find", body={"entity_type": "Item"}, target=target)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["basic", "pat", "m2m"])
async def test_missing_credential_refuses_before_the_verb(mode: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"session_id": "should-not-mint"})

    port, http = _bind(_endpoint(mode), _secrets(mode, value=None), handler)
    try:
        with pytest.raises(AuthError):
            await _verb(port, LAB)
    finally:
        await http.aclose()
    assert not any(request.url.path.endswith("/find") for request in seen)
    assert not any("dev_no_auth" in str(request.url) for request in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "secret"),
    [("basic", "bad-password"), ("pat", "zeus_pat_unknown"), ("m2m", "s3cret-m2m")],
)
async def test_wrong_secret_or_expired_jwt_returns_401(mode: str, secret: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "dev_no_auth" not in str(request.url)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "jwt-expired"})
        if request.url.path.endswith("/auth/session"):
            return httpx.Response(401, json={"error": "unauthenticated"})
        raise AssertionError(request.url.path)

    port, http = _bind(_endpoint(mode), _secrets(mode, value=secret), handler)
    try:
        with pytest.raises(AuthError) as ei:
            await _verb(port, LAB)
    finally:
        await http.aclose()
    assert ei.value.details["status_code"] == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "secret"),
    [("basic", "good-password"), ("pat", "zeus_pat_good"), ("m2m", "s3cret-m2m")],
)
async def test_good_mint_then_one_v2_verb_returns_200(mode: str, secret: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert "dev_no_auth" not in str(request.url)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "eyJ.good.sig"})
        if request.url.path == "/v1/lab/security/auth/session":
            return httpx.Response(200, json={"session_id": "sess_good_123", "expires_in": 1800})
        if request.url.path == "/v2/lab/security/items/find":
            assert request.headers["X-Zeus-Session"] == "sess_good_123"
            return httpx.Response(
                200,
                json={"result": {"node_ids": ["n1"]}},
                headers={"X-Zeus-Req-Id": "req-matrix"},
            )
        raise AssertionError(request.url.path)

    port, http = _bind(_endpoint(mode), _secrets(mode, value=secret), handler)
    try:
        result = await _verb(port, LAB)
    finally:
        await http.aclose()
    assert result.ok and result.status_code == 200
    assert any(request.url.path == "/v1/lab/security/auth/session" for request in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["basic", "pat", "m2m"])
async def test_cross_scope_does_not_reuse_the_other_session(mode: str) -> None:
    secret = {"basic": "good-password", "pat": "zeus_pat_good", "m2m": "s3cret-m2m"}[mode]
    sids = {"lab/security": "sess_scope_a_123", "lab/other": "sess_scope_b_456"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert "dev_no_auth" not in str(request.url)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "eyJ.good.sig"})
        if request.url.path.endswith("/auth/session"):
            sid = sids[_scope_of(request.url.path)]
            assert (
                request.headers.get("X-Zeus-Session") != sids["lab/security"]
                or _scope_of(request.url.path) == "lab/security"
            )
            return httpx.Response(200, json={"session_id": sid, "expires_in": 1800})
        if request.url.path.endswith("/find"):
            scope = "/".join(request.url.path.split("/")[2:4])
            assert request.headers["X-Zeus-Session"] == sids[scope]
            return httpx.Response(200, json={"result": {}}, headers={"X-Zeus-Req-Id": "req"})
        raise AssertionError(request.url.path)

    port, http = _bind(_endpoint(mode), _secrets(mode, value=secret), handler)
    try:
        first = await _verb(port, LAB)
        second = await _verb(port, OTHER)
    finally:
        await http.aclose()
    assert first.ok and second.ok


@pytest.mark.asyncio
async def test_revoke_pat_returns_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer zeus_pat_revoked"
        return httpx.Response(401, json={"error": "unauthenticated"})

    resolver = ZeusAuthResolver(
        endpoint=_endpoint("pat"),
        secrets=_secrets("pat", value="zeus_pat_revoked"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(LAB)
    assert ei.value.details["status_code"] == 401
    await resolver.client.aclose()


@pytest.mark.asyncio
async def test_lockout_basic_returns_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/lab/security/auth/session"
        return httpx.Response(429, json={"error": "rate_limited"})

    resolver = ZeusAuthResolver(
        endpoint=_endpoint("basic"),
        secrets=_secrets("basic", value="good-password"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(LAB)
    assert ei.value.details["status_code"] == 429
    await resolver.client.aclose()


@pytest.mark.asyncio
async def test_issuer_unset_m2m_does_not_call_zeus() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    resolver = ZeusAuthResolver(
        endpoint=_endpoint("m2m", issuer=""),
        secrets=_secrets("m2m", value="s3cret-m2m"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(LAB)
    assert "issuer is unset" in ei.value.public_message
    await resolver.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["jwt-wrong-aud", "jwt-wrong-iss"])
async def test_wrong_aud_or_iss_returns_401(token: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": token})
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(401, json={"error": "unauthenticated"})

    resolver = ZeusAuthResolver(
        endpoint=_endpoint("m2m"),
        secrets=_secrets("m2m", value="s3cret-m2m"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AuthError) as ei:
        await resolver.resolve(LAB)
    assert ei.value.details["status_code"] == 401
    await resolver.client.aclose()
