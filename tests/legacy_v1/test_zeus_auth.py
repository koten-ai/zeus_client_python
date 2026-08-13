"""Tests for python3/zeus/auth.py — session cache and auth resolution."""

import time

import httpx
import pytest
import respx
from zeus_client.zeus.auth import (
    _SESSION_CACHE,
    _SESSION_IDLE_MARGIN_S,
    invalidate_zeus_session,
    resolve_zeus_auth,
)

ZEUS_URL = "http://zeus.test:8080"
BUCKET = "beer-sample"
SCOPE = "_default"


@pytest.fixture(autouse=True)
def _respx(respx_mock):
    yield


@pytest.fixture
def basic_zcfg():
    return {
        "auth_mode": "basic",
        "username": "admin",
        "password": "secret",
    }


def _login_route():
    return respx.post(f"{ZEUS_URL}/v1/{BUCKET}/{SCOPE}/auth/session")


@pytest.mark.asyncio
async def test_auth_mode_none(reset_auth_cache):
    headers, note = await resolve_zeus_auth(ZEUS_URL, {"auth_mode": "none"}, BUCKET, SCOPE)
    assert headers == {}
    assert "no auth" in note


@pytest.mark.asyncio
async def test_auth_mode_bearer_success(reset_auth_cache):
    zcfg = {"auth_mode": "bearer", "bearer_token": "tok-abc"}
    headers, note = await resolve_zeus_auth(ZEUS_URL, zcfg, BUCKET, SCOPE)
    assert headers == {"Authorization": "Bearer tok-abc"}
    assert note == "bearer token"


@pytest.mark.asyncio
async def test_auth_mode_bearer_empty_raises(reset_auth_cache):
    with pytest.raises(RuntimeError, match="bearer_token is empty"):
        await resolve_zeus_auth(ZEUS_URL, {"auth_mode": "bearer"}, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_auth_mode_session_success(reset_auth_cache):
    zcfg = {"auth_mode": "session", "session_id": "sid-xyz"}
    headers, note = await resolve_zeus_auth(ZEUS_URL, zcfg, BUCKET, SCOPE)
    assert headers == {"X-Zeus-Session": "sid-xyz"}
    assert note == "session id"


@pytest.mark.asyncio
async def test_auth_mode_session_empty_raises(reset_auth_cache):
    with pytest.raises(RuntimeError, match="session_id is empty"):
        await resolve_zeus_auth(ZEUS_URL, {"auth_mode": "session"}, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_missing_bucket_scope_raises(reset_auth_cache, basic_zcfg):
    with pytest.raises(RuntimeError, match="basic mode needs a bucket"):
        await resolve_zeus_auth(ZEUS_URL, basic_zcfg, bucket=None, scope=SCOPE)


@pytest.mark.asyncio
async def test_basic_missing_credentials_raises(reset_auth_cache):
    zcfg = {"auth_mode": "basic", "username": "", "password": ""}
    with pytest.raises(RuntimeError, match="no credentials for scope"):
        await resolve_zeus_auth(ZEUS_URL, zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_scope_credentials_precedence(reset_auth_cache, http_client):
    zcfg = {
        "auth_mode": "basic",
        "username": "global",
        "password": "global-pw",
        "scope_credentials": {
            f"{BUCKET}/{SCOPE}": {"username": "scoped", "password": "scoped-pw"},
        },
    }
    route = _login_route()
    route.mock(
        return_value=httpx.Response(
            200,
            json={"session_id": "sid-scoped", "expires_in": 1800, "hard_ttl_s": 43200},
        )
    )
    headers, note = await resolve_zeus_auth(ZEUS_URL, zcfg, BUCKET, SCOPE)
    assert headers["X-Zeus-Session"] == "sid-scoped"
    assert "basic→session" in note
    import base64

    auth_hdr = route.calls.last.request.headers.get("Authorization", "")
    expected = base64.b64encode(b"scoped:scoped-pw").decode()
    assert auth_hdr == f"Basic {expected}"


@pytest.mark.asyncio
async def test_basic_login_success_and_cache(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(
        return_value=httpx.Response(
            200,
            json={"session_id": "sid-fresh-12345", "expires_in": 3600, "hard_ttl_s": 7200},
        )
    )
    headers1, note1 = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert headers1["X-Zeus-Session"] == "sid-fresh-12345"
    assert "(cached)" not in note1
    assert route.call_count == 1

    headers2, note2 = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert headers2["X-Zeus-Session"] == "sid-fresh-12345"
    assert "(cached)" in note2
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_basic_login_default_ttl_when_omitted(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(return_value=httpx.Response(200, json={"session_id": "sid-defaults"}))
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    cache_key = (ZEUS_URL, BUCKET, SCOPE, "admin")
    ent = _SESSION_CACHE[cache_key]
    assert ent["idle_ttl"] == 1800.0
    assert ent["hard_deadline"] > time.time()


@pytest.mark.asyncio
async def test_basic_cache_bypassed_when_force(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(
        side_effect=[
            httpx.Response(200, json={"session_id": "sid-one"}),
            httpx.Response(200, json={"session_id": "sid-two"}),
        ]
    )
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    headers, _ = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE, force=True)
    assert headers["X-Zeus-Session"] == "sid-two"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_basic_cache_miss_wrong_password(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(return_value=httpx.Response(200, json={"session_id": "sid-a"}))
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)

    basic_zcfg["password"] = "other-pw"
    route.mock(return_value=httpx.Response(200, json={"session_id": "sid-b"}))
    headers, _ = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert headers["X-Zeus-Session"] == "sid-b"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_basic_cache_miss_idle_expired(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(
        side_effect=[
            httpx.Response(200, json={"session_id": "sid-old", "expires_in": 60}),
            httpx.Response(200, json={"session_id": "sid-new", "expires_in": 60}),
        ]
    )
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    cache_key = (ZEUS_URL, BUCKET, SCOPE, "admin")
    _SESSION_CACHE[cache_key]["last_used"] = time.time() - 100

    headers, _ = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert headers["X-Zeus-Session"] == "sid-new"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_basic_cache_miss_hard_deadline(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(
        side_effect=[
            httpx.Response(200, json={"session_id": "sid-old"}),
            httpx.Response(200, json={"session_id": "sid-new"}),
        ]
    )
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    cache_key = (ZEUS_URL, BUCKET, SCOPE, "admin")
    _SESSION_CACHE[cache_key]["hard_deadline"] = time.time() - 1

    headers, _ = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert headers["X-Zeus-Session"] == "sid-new"


@pytest.mark.asyncio
async def test_basic_cache_hit_updates_last_used(reset_auth_cache, http_client, basic_zcfg):
    route = _login_route()
    route.mock(return_value=httpx.Response(200, json={"session_id": "sid-live"}))
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    cache_key = (ZEUS_URL, BUCKET, SCOPE, "admin")
    old_last = _SESSION_CACHE[cache_key]["last_used"]
    time.sleep(0.01)
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert _SESSION_CACHE[cache_key]["last_used"] > old_last


@pytest.mark.asyncio
async def test_basic_login_http_error(reset_auth_cache, http_client, basic_zcfg):
    _login_route().mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(RuntimeError, match="Zeus unreachable"):
        await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_login_non_200(reset_auth_cache, http_client, basic_zcfg):
    _login_route().mock(return_value=httpx.Response(401, text="bad creds"))
    with pytest.raises(RuntimeError, match="Zeus login failed"):
        await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_login_nginx_html_401(reset_auth_cache, http_client, basic_zcfg):
    html = "<html><head><title>401 Authorization Required</title></head><body><center>nginx/1.31.1</center></body></html>"
    _login_route().mock(
        return_value=httpx.Response(
            401,
            text=html,
            headers={"Server": "nginx/1.31.1", "WWW-Authenticate": 'Basic realm="Zeus Client"'},
        )
    )
    with pytest.raises(RuntimeError, match="nginx reverse proxy"):
        await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_login_rejects_client_url(reset_auth_cache, basic_zcfg):
    with pytest.raises(RuntimeError, match="9999"):
        await resolve_zeus_auth("http://host:9999", basic_zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_login_proxy_auth_must_match_zeus(reset_auth_cache, basic_zcfg):
    basic_zcfg["proxy_auth"] = {"username": "nginx", "password": "nginx-pw"}
    with pytest.raises(RuntimeError, match="proxy_auth credentials differ"):
        await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_basic_login_missing_session_id(reset_auth_cache, http_client, basic_zcfg):
    _login_route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(RuntimeError, match="no session_id"):
        await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_unknown_auth_mode_raises(reset_auth_cache):
    with pytest.raises(RuntimeError, match="unknown auth mode"):
        await resolve_zeus_auth(ZEUS_URL, {"auth_mode": "oauth"}, BUCKET, SCOPE)


@pytest.mark.asyncio
async def test_invalidate_zeus_session(reset_auth_cache, http_client, basic_zcfg):
    _login_route().mock(return_value=httpx.Response(200, json={"session_id": "sid-x"}))
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    cache_key = (ZEUS_URL, BUCKET, SCOPE, "admin")
    assert cache_key in _SESSION_CACHE

    await invalidate_zeus_session(ZEUS_URL, BUCKET, SCOPE, "admin")
    assert cache_key not in _SESSION_CACHE


@pytest.mark.asyncio
async def test_cache_margin_boundary(reset_auth_cache, http_client, basic_zcfg):
    """Session is still valid when within idle_ttl - margin."""
    route = _login_route()
    route.mock(
        return_value=httpx.Response(
            200,
            json={"session_id": "sid-margin", "expires_in": 120},
        )
    )
    await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    cache_key = (ZEUS_URL, BUCKET, SCOPE, "admin")
    ent = _SESSION_CACHE[cache_key]
    ent["last_used"] = time.time() - (ent["idle_ttl"] - _SESSION_IDLE_MARGIN_S - 5)

    headers, note = await resolve_zeus_auth(ZEUS_URL, basic_zcfg, BUCKET, SCOPE)
    assert "(cached)" in note
    assert route.call_count == 1
