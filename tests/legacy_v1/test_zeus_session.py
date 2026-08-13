"""Tests for python3/zeus/session.py — durable session + trace APIs."""

import json

import httpx
import pytest
import respx
from zeus_client.zeus.session import (
    continue_session_turn,
    create_zeus_session,
    post_session_trace,
    rehydrate_session,
)

ZEUS_URL = "http://zeus.test:8080"
HEADERS = {"X-Zeus-Session": "sid-auth"}
SID = "sess-abc123"


@pytest.fixture(autouse=True)
def _respx(respx_mock):
    yield


@pytest.mark.asyncio
async def test_create_zeus_session_success_200(http_client):
    route = respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            200,
            json={"session_id": SID, "round": 1, "contract_status": "match"},
            headers={"X-Zeus-Req-Id": "creq-1"},
        )
    )
    status, body, url, req_id = await create_zeus_session(
        ZEUS_URL,
        "b",
        "s",
        "cid",
        "chash",
        {"tools": []},
        [{"role": "user", "content": "hi"}],
        HEADERS,
    )
    assert status == 200
    assert body["session_id"] == SID
    assert body["_req_id"] == "creq-1"
    assert url == f"{ZEUS_URL}/v2/session"
    assert req_id == "creq-1"
    payload = json.loads(route.calls.last.request.content)
    assert payload["contract_id"] == "cid"
    assert payload["conversation"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_create_zeus_session_success_201(http_client):
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(201, json={"session_id": SID})
    )
    status, body, _, _ = await create_zeus_session(
        ZEUS_URL,
        "b",
        "s",
        None,
        None,
        None,
        None,
        HEADERS,
    )
    assert status == 201
    assert body["session_id"] == SID


@pytest.mark.asyncio
async def test_create_zeus_session_non_dict_json_body(http_client):
    respx.post(f"{ZEUS_URL}/v2/session").mock(return_value=httpx.Response(200, json=[1, 2]))
    status, body, _, _ = await create_zeus_session(
        ZEUS_URL,
        "b",
        "s",
        "",
        "",
        {},
        [],
        HEADERS,
    )
    assert status == 200
    assert body["raw"] == [1, 2]
    assert "_req_id" in body


@pytest.mark.asyncio
async def test_create_zeus_session_invalid_json_on_success(http_client):
    respx.post(f"{ZEUS_URL}/v2/session").mock(return_value=httpx.Response(200, text="not-json"))
    status, body, _, _ = await create_zeus_session(
        ZEUS_URL,
        "b",
        "s",
        "",
        "",
        {},
        [],
        HEADERS,
    )
    assert status == 200
    assert body["raw"] == "not-json"


@pytest.mark.asyncio
async def test_create_zeus_session_non_2xx(http_client):
    respx.post(f"{ZEUS_URL}/v2/session").mock(return_value=httpx.Response(409, text="conflict"))
    status, body, _, req_id = await create_zeus_session(
        ZEUS_URL,
        "b",
        "s",
        "c",
        "h",
        {},
        [],
        HEADERS,
    )
    assert status == 409
    assert body == "conflict"
    assert req_id == ""


@pytest.mark.asyncio
async def test_create_zeus_session_http_error(http_client):
    respx.post(f"{ZEUS_URL}/v2/session").mock(side_effect=httpx.ConnectError("down"))
    status, body, url, req_id = await create_zeus_session(
        ZEUS_URL,
        "b",
        "s",
        "",
        "",
        {},
        [],
        HEADERS,
    )
    assert status == 0
    assert json.loads(body)["error"] == "session_create_failed"
    assert url == f"{ZEUS_URL}/v2/session"
    assert req_id == ""


@pytest.mark.asyncio
async def test_continue_session_turn_empty_sid():
    status, body, url, req_id = await continue_session_turn(
        ZEUS_URL,
        "",
        2,
        {},
        [],
        HEADERS,
    )
    assert status == 0
    assert body == "no session_id"
    assert url == ""
    assert req_id == ""


@pytest.mark.asyncio
async def test_continue_session_turn_success(http_client):
    route = respx.post(f"{ZEUS_URL}/v2/session/{SID}/turn").mock(
        return_value=httpx.Response(
            200,
            json={"round": 2},
            headers={"X-Zeus-Req-Id": "treq-1"},
        )
    )
    status, body, url, req_id = await continue_session_turn(
        ZEUS_URL,
        SID,
        2,
        {"mode": "auto"},
        [{"role": "assistant", "content": "ok"}],
        HEADERS,
    )
    assert status == 200
    assert body["round"] == 2
    assert body["_req_id"] == "treq-1"
    assert url.endswith(f"/v2/session/{SID}/turn")
    assert req_id == "treq-1"
    payload = json.loads(route.calls.last.request.content)
    assert payload["round"] == 2
    assert payload["new_turns"] == [{"role": "assistant", "content": "ok"}]


@pytest.mark.asyncio
async def test_continue_session_turn_non_200(http_client):
    respx.post(f"{ZEUS_URL}/v2/session/{SID}/turn").mock(
        return_value=httpx.Response(400, text="bad")
    )
    status, body, _, _ = await continue_session_turn(ZEUS_URL, SID, 2, {}, [], HEADERS)
    assert status == 400
    assert body == "bad"


@pytest.mark.asyncio
async def test_continue_session_turn_invalid_json(http_client):
    respx.post(f"{ZEUS_URL}/v2/session/{SID}/turn").mock(
        return_value=httpx.Response(200, text="nope")
    )
    status, body, _, _ = await continue_session_turn(ZEUS_URL, SID, 2, {}, [], HEADERS)
    assert status == 200
    assert body["raw"] == "nope"


@pytest.mark.asyncio
async def test_continue_session_turn_http_error(http_client):
    respx.post(f"{ZEUS_URL}/v2/session/{SID}/turn").mock(side_effect=httpx.ReadTimeout("slow"))
    status, body, url, req_id = await continue_session_turn(ZEUS_URL, SID, 2, {}, [], HEADERS)
    assert status == 0
    assert json.loads(body)["error"] == "session_turn_failed"
    assert url.endswith("/turn")
    assert req_id == ""


@pytest.mark.asyncio
async def test_post_session_trace_bad_params():
    status, body, url, req_id = await post_session_trace(
        ZEUS_URL,
        "",
        0,
        "r",
        "",
        "",
        {},
        [],
        {},
        "ok",
        HEADERS,
    )
    assert status == 0
    assert body == "bad trace params"
    assert url == ""
    assert req_id == ""

    status, body, _, _ = await post_session_trace(
        ZEUS_URL,
        SID,
        0,
        "r",
        "",
        "",
        {},
        [],
        {},
        "ok",
        HEADERS,
    )
    assert status == 0
    assert body == "bad trace params"


@pytest.mark.asyncio
async def test_post_session_trace_success(http_client):
    route = respx.post(f"{ZEUS_URL}/v2/session/trace").mock(
        return_value=httpx.Response(
            201,
            json={"ok": True},
            headers={"X-Zeus-Req-Id": "trace-1"},
        )
    )
    status, body, url, req_id = await post_session_trace(
        ZEUS_URL,
        SID,
        2,
        "req-join",
        "cid",
        "chash",
        {"x": 1},
        [{"role": "tool", "content": "find → 200"}],
        {"status": 200},
        "ok",
        HEADERS,
    )
    assert status == 201
    assert body["ok"] is True
    assert body["_req_id"] == "trace-1"
    assert url == f"{ZEUS_URL}/v2/session/trace"
    assert req_id == "trace-1"
    payload = json.loads(route.calls.last.request.content)
    assert payload["session_id"] == SID
    assert payload["round"] == 2
    assert payload["outcome"] == "ok"


@pytest.mark.asyncio
async def test_post_session_trace_non_success(http_client):
    respx.post(f"{ZEUS_URL}/v2/session/trace").mock(return_value=httpx.Response(500, text="fail"))
    status, body, _, _ = await post_session_trace(
        ZEUS_URL,
        SID,
        1,
        "",
        "",
        "",
        None,
        None,
        None,
        None,
        HEADERS,
    )
    assert status == 500
    assert body == "fail"


@pytest.mark.asyncio
async def test_post_session_trace_invalid_json(http_client):
    respx.post(f"{ZEUS_URL}/v2/session/trace").mock(return_value=httpx.Response(200, text="raw"))
    status, body, _, _ = await post_session_trace(
        ZEUS_URL,
        SID,
        1,
        "",
        "",
        "",
        {},
        [],
        {},
        "ok",
        HEADERS,
    )
    assert status == 200
    assert body["raw"] == "raw"


@pytest.mark.asyncio
async def test_post_session_trace_http_error(http_client):
    respx.post(f"{ZEUS_URL}/v2/session/trace").mock(side_effect=httpx.ConnectError("x"))
    status, body, url, req_id = await post_session_trace(
        ZEUS_URL,
        SID,
        1,
        "",
        "",
        "",
        {},
        [],
        {},
        "ok",
        HEADERS,
    )
    assert status == 0
    assert json.loads(body)["error"] == "session_trace_failed"
    assert url == f"{ZEUS_URL}/v2/session/trace"
    assert req_id == ""


@pytest.mark.asyncio
async def test_rehydrate_session_empty_sid():
    assert await rehydrate_session(ZEUS_URL, "") is None


@pytest.mark.asyncio
async def test_rehydrate_session_success(http_client):
    doc = {"session_id": SID, "round": 3, "conversation": [{"role": "user", "content": "hi"}]}
    respx.get(f"{ZEUS_URL}/v2/session/{SID}?rounds=6").mock(
        return_value=httpx.Response(200, json=doc),
    )
    result = await rehydrate_session(ZEUS_URL, SID, rounds=6, zeus_headers=HEADERS)
    assert result == doc


@pytest.mark.asyncio
async def test_rehydrate_session_invalid_json(http_client):
    respx.get(f"{ZEUS_URL}/v2/session/{SID}?rounds=4").mock(
        return_value=httpx.Response(200, text="not-json"),
    )
    assert await rehydrate_session(ZEUS_URL, SID, rounds=4) is None


@pytest.mark.asyncio
async def test_rehydrate_session_non_200(http_client):
    respx.get(f"{ZEUS_URL}/v2/session/{SID}?rounds=6").mock(
        return_value=httpx.Response(404, text="missing"),
    )
    assert await rehydrate_session(ZEUS_URL, SID) is None


@pytest.mark.asyncio
async def test_rehydrate_session_http_error(http_client):
    respx.get(f"{ZEUS_URL}/v2/session/{SID}?rounds=6").mock(
        side_effect=httpx.ConnectError("down"),
    )
    assert await rehydrate_session(ZEUS_URL, SID) is None
