"""Session create, turn, and trace send bucket and scope only when both are set."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.session import HttpxSessionClient, scope_fields
from zeus_client.application.projectors.session_trace import project_session_trace
from zeus_client.application.session_lifecycle import SessionLifecycle
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.session import SessionHandle

ZEUS = "http://zeus.test:8080"
TARGET = DataTarget(bucket="yelp-demo", scope="_default", collection="businesses")


def test_scope_fields_omits_missing_or_partial_target() -> None:
    assert scope_fields(None) == {}
    assert scope_fields(DataTarget(bucket="yelp-demo", scope="")) == {}
    assert scope_fields(DataTarget(bucket="  ", scope="_default")) == {}
    assert scope_fields(TARGET) == {"bucket": "yelp-demo", "scope": "_default"}


@pytest.mark.asyncio
@respx.mock
async def test_session_json_includes_bucket_and_scope_when_target_passed() -> None:
    create = respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(201, json={"session_id": "sid", "round": 1})
    )
    turn = respx.post(f"{ZEUS}/v2/session/sid/turn").mock(
        return_value=httpx.Response(200, json={"session_id": "sid", "round": 2})
    )
    trace = respx.post(f"{ZEUS}/v2/session/trace").mock(
        return_value=httpx.Response(201, json={"contract_status": "match"})
    )
    client = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    await client.create(
        contract_id="cid",
        contract_hash="md5:aaa",
        chat_request={},
        conversation=[],
        target=TARGET,
    )
    await client.continue_turn(
        session_id="sid",
        client_round=2,
        chat_request={},
        new_turns=[{"role": "assistant", "content": "ok"}],
        target=TARGET,
    )
    await client.post_trace(
        session_id="sid",
        client_round=1,
        req_id="req-1",
        contract_id="cid",
        contract_hash="md5:aaa",
        chat_request={},
        turns=[],
        zeus_response={"status": 200},
        target=TARGET,
    )
    for route in (create, turn, trace):
        body = json.loads(route.calls.last.request.content)
        assert body["bucket"] == "yelp-demo"
        assert body["scope"] == "_default"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_session_json_omits_scope_when_target_missing() -> None:
    route = respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(201, json={"session_id": "sid", "round": 1})
    )
    client = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    await client.create(
        contract_id="cid",
        contract_hash="md5:aaa",
        chat_request={},
        conversation=[],
    )
    body = json.loads(route.calls.last.request.content)
    assert "bucket" not in body
    assert "scope" not in body
    assert "yelp-data" not in route.calls.last.request.content.decode()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_threads_target_onto_create_and_turn() -> None:
    create = respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sid-1", "round": 1, "contract_status": "match"},
        )
    )
    turn = respx.post(f"{ZEUS}/v2/session/sid-1/turn").mock(
        return_value=httpx.Response(200, json={"session_id": "sid-1", "round": 2})
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http, target=TARGET)
    handle = await life.setup(
        chat_request={"messages": [{"role": "system", "content": "rules"}]},
        user_message="hello",
        contract_id="c1",
        mode="analytics",
    )
    await life.commit(
        handle,
        chat_request={},
        produced_delta=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
        ],
    )
    create_body = json.loads(create.calls.last.request.content)
    turn_body = json.loads(turn.calls.last.request.content)
    assert create_body["bucket"] == "yelp-demo"
    assert create_body["scope"] == "_default"
    assert turn_body["bucket"] == "yelp-demo"
    assert turn_body["scope"] == "_default"
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_projector_threads_target_onto_trace() -> None:
    route = respx.post(f"{ZEUS}/v2/session/trace").mock(
        return_value=httpx.Response(200, json={"contract_status": "match"})
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    handle = SessionHandle(
        session_id="sid-1",
        round=1,
        enabled=True,
        contract_id="c",
        contract_hash="h",
    )
    result = await project_session_trace(
        http,
        handle=handle,
        hops=[{"req_id": "r1", "name": "find", "status": 200}],
        chat_request={},
        target=TARGET,
    )
    assert result.ok
    body = json.loads(route.calls.last.request.content)
    assert body["bucket"] == "yelp-demo"
    assert body["scope"] == "_default"
    await http.aclose()
