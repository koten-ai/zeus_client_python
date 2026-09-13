"""Contract tests for V2 Zeus HTTP verbs + data API (ZCP-9)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.headers import apply_mode_header
from zeus_client.adapters.zeus_http.verbs import (
    EXPOSED_V2_VERBS,
    HttpxZeusPort,
    verb_allows_sdk_retry,
    verb_url,
    zeus_hop_retryable,
)
from zeus_client.application.data_verb import run_data_verb
from zeus_client.config.models import DataTarget, RetryPolicy, RuntimeConfig, ZeusEndpointConfig
from zeus_client.domain.errors import ErrorCode, ZeusToolError
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.domain.journal.events import EVENT_ZEUS_HOP
from zeus_client.runtime import ZeusRuntime


def test_exposed_verbs_exclude_pipeline() -> None:
    assert "pipeline" not in EXPOSED_V2_VERBS
    assert "find" in EXPOSED_V2_VERBS
    assert "search" in EXPOSED_V2_VERBS


def test_verb_url_shapes() -> None:
    t = DataTarget(bucket="yelp-data", scope="_default", collection="_default")
    assert verb_url("http://z:8080", t, "find").endswith("/v2/yelp-data/_default/_default/find")
    assert verb_url("http://z:8080", t, "explain").endswith("/v2/explain")
    assert verb_url("http://z:8080", t, "describe").endswith("/v2/yelp-data/_default/describe")


def test_mode_header_always_set() -> None:
    h = apply_mode_header({}, "analytics")
    assert h["X-Zeus-Mode"] == "analytics"
    h2 = apply_mode_header({"X-Zeus-Mode": "chat"}, "analytics")
    assert h2["X-Zeus-Mode"] == "chat"


@pytest.mark.asyncio
@respx.mock
async def test_find_verb_captures_req_id_and_journals() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(f"{base}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(
            200,
            json={"result": {"node_ids": ["n1"]}},
            headers={"X-Zeus-Req-Id": "req-abc-123"},
        )
    )
    journal = InMemoryJournal()
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        journal=journal,
        turn_id="turn_t",
    )
    try:
        result = await run_data_verb(
            port,
            "find",
            {"entity_type": "Business", "limit": 1},
            target=DataTarget(),
            mode_header="analytics",
        )
    finally:
        await port.aclose()

    assert route.called
    req = route.calls.last.request
    assert req.headers.get("X-Zeus-Mode") == "analytics"
    assert result.ok
    assert result.req_id == "req-abc-123"
    hops = [e for e in journal.events() if e.type == EVENT_ZEUS_HOP]
    assert len(hops) == 1
    assert hops[0].data["req_id"] == "req-abc-123"
    assert "Authorization" not in json.dumps(hops[0].data.get("headers", {})) or hops[0].data[
        "headers"
    ].get("Authorization") in (None, "[REDACTED]")


@pytest.mark.asyncio
@respx.mock
async def test_4xx_still_captures_req_id() -> None:
    base = "http://zeus.test:8080"
    respx.post(url__startswith=f"{base}/v2/").mock(
        return_value=httpx.Response(
            400,
            json={"error": "bad"},
            headers={"X-Zeus-Req-Id": "req-err-9"},
        )
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        journal=InMemoryJournal(),
        turn_id="t",
    )
    try:
        r = await run_data_verb(port, "get", {}, target=DataTarget())
    finally:
        await port.aclose()
    assert r.ok is False
    assert r.status_code == 400
    assert r.req_id == "req-err-9"


@pytest.mark.asyncio
async def test_pipeline_rejected_on_public_api() -> None:
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url="http://z", auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    with pytest.raises(ZeusToolError) as ei:
        await run_data_verb(port, "pipeline", {}, target=DataTarget())
    assert ei.value.code is ErrorCode.ZEUS_PIPELINE_NOT_ON_DIRECT
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_runtime_data_verb_wiring() -> None:
    base = "http://zeus.test:8080"
    respx.post(url__startswith=f"{base}/v2/").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r1"})
    )
    cfg = RuntimeConfig(zeus=ZeusEndpointConfig(url=base, auth_mode="none"))
    journal = InMemoryJournal()
    port = HttpxZeusPort(
        endpoint=cfg.zeus,
        secrets=EnvSecretStore(environ={}),
        journal=journal,
        turn_id="turn_rt",
    )
    async with ZeusRuntime(cfg, zeus=port, journal=journal) as rt:
        result = await rt.data.find({"entity_type": "Business", "limit": 2})
        assert result.ok
        assert result.req_id == "r1"


@pytest.mark.asyncio
@respx.mock
async def test_basic_auth_never_logs_password() -> None:
    secrets = EnvSecretStore(environ={"ZEUS_PASSWORD": "s3cret-pass"})
    respx.post("http://z/v1/yelp-data/_default/auth/session").mock(
        return_value=httpx.Response(200, json={"session_id": "sess_lab"})
    )
    journal = InMemoryJournal()
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(
            url="http://z",
            auth_mode="basic",
            username="admin",
            password_env="ZEUS_PASSWORD",
        ),
        secrets=secrets,
        journal=journal,
    )
    auth = await port.resolve_auth(DataTarget())
    assert auth.headers.get("X-Zeus-Session") == "sess_lab"
    dumped = json.dumps([e.data for e in journal.events()])
    assert "s3cret-pass" not in dumped
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_data_verb_stamps_direct_read_class() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(f"{base}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-dr"})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    try:
        await run_data_verb(port, "find", {"entity_type": "Business"}, target=DataTarget())
    finally:
        await port.aclose()
    h = route.calls.last.request.headers
    assert h["X-Zeus-Trace-Class"] == "direct.read"
    assert h.get("X-Zeus-Req-Id") in (None, "")


@pytest.mark.asyncio
@respx.mock
async def test_per_call_base_url_posts_to_override_host() -> None:
    process = "http://zeus.test:8080"
    unit = "http://zeus-b:8080"
    route_unit = respx.post(f"{unit}/v2/east/sales/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-b"})
    )
    route_process = respx.post(f"{process}/v2/east/sales/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-a"})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=process, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    try:
        r = await run_data_verb(
            port,
            "find",
            {"entity_type": "Beer"},
            target=DataTarget(bucket="east", scope="sales", collection="_default"),
            base_url=unit,
        )
    finally:
        await port.aclose()
    assert r.ok
    assert r.req_id == "r-b"
    assert route_unit.called
    assert not route_process.called


@pytest.mark.asyncio
@respx.mock
async def test_per_call_password_env_name_used_and_secret_not_journaled() -> None:
    base = "http://zeus.test:8080"
    mint = respx.post(f"{base}/v1/east/sales/auth/session").mock(
        return_value=httpx.Response(200, json={"session_id": "sess_east"})
    )
    route = respx.post(f"{base}/v2/east/sales/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-auth"})
    )
    journal = InMemoryJournal()
    secrets = EnvSecretStore(
        environ={"ZEUS_PASSWORD": "process-secret", "ZEUS_EAST_PASSWORD": "east-secret"}
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(
            url=base,
            auth_mode="basic",
            username="admin",
            password_env="ZEUS_PASSWORD",
        ),
        secrets=secrets,
        journal=journal,
        turn_id="t",
    )
    try:
        await run_data_verb(
            port,
            "find",
            {"entity_type": "Beer"},
            target=DataTarget(bucket="east", scope="sales", collection="_default"),
            auth_mode="basic",
            username="east-user",
            password_env="ZEUS_EAST_PASSWORD",
        )
    finally:
        await port.aclose()
    assert mint.called
    assert route.called
    expected = base64.b64encode(b"east-user:east-secret").decode()
    mint_auth = mint.calls.last.request.headers.get("Authorization") or ""
    assert expected in mint_auth
    assert route.calls.last.request.headers.get("X-Zeus-Session") == "sess_east"
    blob = json.dumps([e.data for e in journal.events()])
    assert "east-secret" not in blob
    assert "process-secret" not in blob


@pytest.mark.asyncio
@respx.mock
async def test_http_verb_forwards_rewind_headers() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(f"{base}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-fwd"})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    try:
        await run_data_verb(
            port,
            "find",
            {"entity_type": "Business"},
            target=DataTarget(),
            mode_header="analytics",
            headers={"X-Zeus-Chat-Id": "chat-1", "X-Zeus-Turn-Id": "turn-1"},
        )
    finally:
        await port.aclose()
    req = route.calls.last.request
    assert req.headers["X-Zeus-Chat-Id"] == "chat-1"
    assert req.headers["X-Zeus-Turn-Id"] == "turn-1"
    assert req.headers["X-Zeus-Trace-Class"] == "direct.read"
    assert req.headers["X-Zeus-Mode"] == "analytics"
    assert req.headers.get("X-Zeus-Req-Id") in (None, "")
    assert "rewind=" not in str(req.url)


@pytest.mark.asyncio
@respx.mock
async def test_http_verb_sends_rewind_query_not_body() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(url__startswith=f"{base}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-rw"})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    try:
        await run_data_verb(
            port,
            "find",
            {"entity_type": "Business", "rewind": True},
            target=DataTarget(),
            rewind=True,
        )
    finally:
        await port.aclose()
    req = route.calls.last.request
    assert "rewind=true" in str(req.url)
    body = json.loads(req.content)
    assert "rewind" not in body
    assert body["entity_type"] == "Business"


@pytest.mark.asyncio
@respx.mock
async def test_http_verb_default_omits_rewind_query() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(f"{base}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    try:
        await run_data_verb(
            port,
            "find",
            {"entity_type": "Business"},
            target=DataTarget(),
        )
    finally:
        await port.aclose()
    req = route.calls.last.request
    assert "rewind=" not in str(req.url)
    assert "rewind" not in json.loads(req.content)


def test_verb_sdk_retry_matrix() -> None:
    for v in ("find", "get", "search", "describe", "explain", "traverse"):
        assert verb_allows_sdk_retry(v)
    for v in ("set", "pipeline", "return", "order", "enrich", "project", "analyze"):
        assert not verb_allows_sdk_retry(v)
    assert zeus_hop_retryable("find", status=503, transport_err=False)
    assert zeus_hop_retryable("find", status=0, transport_err=True)
    assert not zeus_hop_retryable("find", status=409, transport_err=False)
    assert not zeus_hop_retryable("find", status=429, transport_err=False)
    assert not zeus_hop_retryable("set", status=503, transport_err=False)


def _retry_port(base: str) -> HttpxZeusPort:
    return HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        retry=RetryPolicy(max_attempts=3, base_delay_ms=0, jitter=False),
    )


@pytest.mark.asyncio
@respx.mock
async def test_find_retries_503_then_ok() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(url__startswith=f"{base}/v2/").mock(
        side_effect=[
            httpx.Response(503, json={"error": "busy"}),
            httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-ok"}),
        ]
    )
    port = _retry_port(base)
    try:
        r = await run_data_verb(port, "find", {}, target=DataTarget())
    finally:
        await port.aclose()
    assert route.call_count == 2
    assert r.ok is True
    assert r.req_id == "r-ok"


@pytest.mark.asyncio
@respx.mock
async def test_find_no_retry_409() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(url__startswith=f"{base}/v2/").mock(
        return_value=httpx.Response(409, json={"error": "contract"}, headers={"X-Zeus-Req-Id": "r-409"})
    )
    port = _retry_port(base)
    try:
        r = await run_data_verb(port, "find", {}, target=DataTarget())
    finally:
        await port.aclose()
    assert route.call_count == 1
    assert r.ok is False
    assert r.status_code == 409


@pytest.mark.asyncio
@respx.mock
async def test_find_no_retry_429() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(url__startswith=f"{base}/v2/").mock(
        return_value=httpx.Response(429, json={"error": "slow"})
    )
    port = _retry_port(base)
    try:
        r = await run_data_verb(port, "find", {}, target=DataTarget())
    finally:
        await port.aclose()
    assert route.call_count == 1
    assert r.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_find_retries_transport_then_ok() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(url__startswith=f"{base}/v2/").mock(
        side_effect=[
            httpx.ConnectError("connection reset"),
            httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": "r-t"}),
        ]
    )
    port = _retry_port(base)
    try:
        r = await run_data_verb(port, "find", {}, target=DataTarget())
    finally:
        await port.aclose()
    assert route.call_count == 2
    assert r.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_set_no_retry_503() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(url__startswith=f"{base}/v2/").mock(
        return_value=httpx.Response(503, json={"error": "busy"})
    )
    port = _retry_port(base)
    try:
        r = await run_data_verb(port, "set", {"doc_key": "x"}, target=DataTarget())
    finally:
        await port.aclose()
    assert route.call_count == 1
    assert r.status_code == 503
