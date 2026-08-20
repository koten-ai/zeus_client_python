"""Session lifecycle oracles (ZCP-14 · Task 5.1).

create / rehydrate / continue / dead-sid same-turn recovery.
Wire shapes aligned with design wire/v2_session_*.json.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.session import HttpxSessionClient
from zeus_client.application.session_lifecycle import (
    SessionLifecycle,
    contract_status_from_rehydrate,
)
from zeus_client.config.models import ZeusEndpointConfig
from zeus_client.domain.session import SessionHandle

ZEUS = "http://zeus.test:8080"
HEADERS = {"X-Zeus-Mode": "analytics"}


def test_contract_status_from_rehydrate_match() -> None:
    assert (
        contract_status_from_rehydrate(
            "cid",
            "md5:aaa",
            {"hash": "md5:aaa", "contract_id": "cid"},
        )
        == "match"
    )


def test_contract_status_from_rehydrate_drift() -> None:
    assert (
        contract_status_from_rehydrate(
            "cid",
            "md5:want",
            {"hash": "md5:other", "contract_id": "cid"},
        )
        == "drift"
    )


def test_contract_status_from_rehydrate_none() -> None:
    assert contract_status_from_rehydrate("", "", {}) == "none"


def test_contract_status_incomplete_hashes_prefer_match() -> None:
    # Binding present but incomplete hash material → match (V1 oracle)
    assert contract_status_from_rehydrate("cid", "", {"contract_id": "cid", "hash": ""}) == "match"


@pytest.mark.asyncio
@respx.mock
async def test_http_create_session_wire_shape() -> None:
    route = respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={
                "session_id": "zsess_mock_turn_001",
                "round": 1,
                "hash": "mock:00000000000000000000000000000000",
                "contract_status": "ok",
                "max_rounds": 16,
            },
            headers={"X-Zeus-Req-Id": "d4000000-0000-4000-8000-000000000004"},
        )
    )
    client = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    result = await client.create(
        contract_id="mock_analytics_b5",
        contract_hash="mock:00000000000000000000000000000000",
        chat_request={"_note": "catalog"},
        conversation=[],
        headers=HEADERS,
    )
    assert result.ok
    assert result.status_code == 201
    assert result.req_id == "d4000000-0000-4000-8000-000000000004"
    assert result.body["session_id"] == "zsess_mock_turn_001"
    assert route.called
    body = route.calls.last.request.read()
    assert b"contract_id" in body
    assert b"chat_request" in body
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_continue_turn_wire_shape() -> None:
    sid = "zsess_mock_turn_001"
    route = respx.post(f"{ZEUS}/v2/session/{sid}/turn").mock(
        return_value=httpx.Response(
            200,
            json={"session_id": sid, "round": 2, "status": "ok"},
            headers={"X-Zeus-Req-Id": "e5000000-0000-4000-8000-000000000005"},
        )
    )
    client = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    result = await client.continue_turn(
        session_id=sid,
        client_round=2,
        chat_request={},
        new_turns=[{"role": "user", "content": "Find fruit beers"}],
        headers=HEADERS,
    )
    assert result.ok and result.status_code == 200
    assert route.called
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_create_new_session() -> None:
    respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={
                "session_id": "sid-new",
                "round": 1,
                "contract_status": "match",
            },
            headers={"X-Zeus-Req-Id": "req-create"},
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    handle = await life.setup(
        chat_request={
            "messages": [{"role": "system", "content": "rules"}],
            "contract": {"hash": "md5:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        },
        user_message="hello",
        prior=None,
        contract_id="c1",
        bound_contract_hash="md5:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        mode="analytics",
        chat_id="chat-1",
    )
    assert isinstance(handle, SessionHandle)
    assert handle.session_id == "sid-new"
    assert handle.round == 1
    assert handle.created is True
    assert handle.contract_status == "match"
    assert handle.create_req_id == "req-create"
    assert handle.chat_id == "chat-1"
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_rehydrate_success() -> None:
    from zeus_client.domain.contract import compute_contract_hash

    sid = "sid-live"
    chat_request = {"messages": [{"role": "system", "content": "x"}]}
    h = compute_contract_hash(chat_request)
    respx.get(f"{ZEUS}/v2/session/{sid}").mock(
        return_value=httpx.Response(
            200,
            json={
                "session_id": sid,
                "round": 2,
                "hash": h,
                "contract_id": "c1",
                "conversation": [{"role": "user", "content": "hi"}],
                "rounds_loaded": 2,
            },
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    prior = SessionHandle(
        session_id=sid,
        round=2,
        chat_id="chat-1",
        contract_id="c1",
        contract_hash=h,
    )
    handle = await life.setup(
        chat_request=chat_request,
        user_message="next",
        prior=prior,
        contract_id="c1",
        bound_contract_hash=h,
        mode="analytics",
        chat_id="chat-1",
    )
    assert handle.session_id == sid
    assert handle.round == 3  # next user round = server + 1
    assert handle.rehydrated is True
    assert handle.created is False
    assert handle.contract_status == "match"
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_dead_sid_recreates_same_turn() -> None:
    dead = "stale-sid"
    respx.get(f"{ZEUS}/v2/session/{dead}").mock(return_value=httpx.Response(404, text="gone"))
    respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={
                "session_id": "sid-recover",
                "round": 1,
                "contract_status": "match",
            },
            headers={"X-Zeus-Req-Id": "req-rec"},
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    prior = SessionHandle(session_id=dead, round=6, chat_id="c")
    handle = await life.setup(
        chat_request={"messages": [{"role": "system", "content": "x"}]},
        user_message="recover me",
        prior=prior,
        contract_id="c1",
        bound_contract_hash="md5:cccccccccccccccccccccccccccccccc",
        mode="analytics",
        chat_id="c",
    )
    assert handle.session_id == "sid-recover"
    assert handle.created is True
    assert handle.recovered_from == dead
    assert handle.round == 1
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_dead_sid_and_create_fail_clears_sid() -> None:
    dead = "stale-2"
    respx.get(f"{ZEUS}/v2/session/{dead}").mock(return_value=httpx.Response(404))
    respx.post(f"{ZEUS}/v2/session").mock(return_value=httpx.Response(500, text="fail"))
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    handle = await life.setup(
        chat_request={},
        user_message="x",
        prior=SessionHandle(session_id=dead, round=1, chat_id="c"),
        contract_id="",
        bound_contract_hash="",
        mode="analytics",
        chat_id="c",
    )
    assert handle.session_id == ""
    assert handle.created is False
    assert handle.recovered_from == dead
    assert handle.error
    await http.aclose()


@pytest.mark.asyncio
async def test_lifecycle_sessions_disabled() -> None:
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    handle = await life.setup(
        chat_request={},
        user_message="x",
        prior=None,
        contract_id="c1",
        bound_contract_hash="md5:x",
        mode="analytics",
        chat_id="c",
        enable_sessions=False,
    )
    assert handle.enabled is False
    assert handle.session_id == ""
    assert handle.contract_id == "c1"
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_commit_continue_turn_just_created() -> None:
    sid = "sid-new"
    route = respx.post(f"{ZEUS}/v2/session/{sid}/turn").mock(
        return_value=httpx.Response(
            200,
            json={"session_id": sid, "round": 2, "status": "ok"},
            headers={"X-Zeus-Req-Id": "turn-req"},
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    handle = SessionHandle(
        session_id=sid,
        round=1,
        chat_id="c",
        contract_id="c1",
        contract_hash="md5:h",
        contract_status="match",
        created=True,
        enabled=True,
    )
    delta = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = await life.commit(
        handle,
        chat_request={},
        produced_delta=delta,
        mode="analytics",
    )
    assert out.ok
    assert out.handle.round == 2
    assert route.called
    # just_created: user turn stripped from new_turns; round = create_round+1
    import json

    body = json.loads(route.calls.last.request.content)
    assert body["round"] == 2
    assert all(t.get("role") != "user" for t in body["new_turns"])
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_prefers_payload_hash_on_drift() -> None:
    """bound stamp drift → session create uses payload hash (avoid 409)."""
    route = respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "s1", "round": 1, "contract_status": "match"},
            headers={"X-Zeus-Req-Id": "r1"},
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    chat = {
        "messages": [{"role": "system", "content": "rules only"}],
        "verbs": [{"type": "function", "function": {"name": "find"}}],
    }
    from zeus_client.domain.contract import compute_contract_hash

    payload_h = compute_contract_hash(chat)
    await life.setup(
        chat_request=chat,
        user_message="hi",
        prior=None,
        contract_id="c1",
        bound_contract_hash="md5:boundddddddddddddddddddddddddddd",
        mode="analytics",
        chat_id="c",
    )
    import json

    body = json.loads(route.calls.last.request.content)
    assert body["contract_hash"] == payload_h
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_create_stamps_session_rewind_headers() -> None:
    route = respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sid-rw", "round": 1, "contract_status": "match"},
            headers={"X-Zeus-Req-Id": "req-create-rw"},
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    await life.setup(
        chat_request={"messages": [{"role": "system", "content": "x"}]},
        user_message="hello",
        prior=None,
        contract_id="c1",
        mode="analytics",
        chat_id="chat-rew",
        turn_id="turn_abc",
        force_trace=True,
    )
    h = route.calls.last.request.headers
    assert h["X-Zeus-Chat-Id"] == "chat-rew"
    assert h["X-Zeus-Turn-Id"] == "turn_abc"
    assert h["X-Zeus-Trace-Class"] == "session"
    assert h["X-Zeus-Trace"] == "1"
    assert "X-Zeus-Call-Id" not in h
    assert route.calls.last.request.headers.get("X-Zeus-Req-Id") in (None, "")
    await http.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_mode_switch_creates_new_session() -> None:
    respx.post(f"{ZEUS}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sid-new-mode", "round": 1, "contract_status": "match"},
        )
    )
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(url=ZEUS),
        secrets=EnvSecretStore({}),
    )
    life = SessionLifecycle(http)
    prior = SessionHandle(
        session_id="sid-old",
        round=3,
        chat_id="c",
        mode="analytics",
    )
    handle = await life.setup(
        chat_request={"messages": [{"role": "system", "content": "x"}]},
        user_message="switch",
        prior=prior,
        mode="explore",
        chat_id="c",
    )
    assert handle.session_id == "sid-new-mode"
    assert handle.created is True
    assert handle.mode == "explore"
    await http.aclose()
