"""Contract tests for V2 Zeus HTTP verbs + data API (ZCP-9)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.headers import apply_mode_header
from zeus_client.adapters.zeus_http.verbs import (
    EXPOSED_V2_VERBS,
    HttpxZeusPort,
    verb_url,
)
from zeus_client.application.data_verb import run_data_verb
from zeus_client.config.models import DataTarget, RuntimeConfig, ZeusEndpointConfig
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
