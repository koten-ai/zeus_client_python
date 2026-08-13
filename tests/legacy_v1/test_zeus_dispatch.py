"""Tests for python3/zeus/dispatch.py — V1/V2 tool dispatch."""
import json

import httpx
import pytest
import respx

from zeus_client.zeus.dispatch import (
    dispatch_zeus_call,
    dispatch_zeus_tool,
    dispatch_zeus_v2_verb,
    zeus_correlation_headers,
)

ZEUS_URL = "http://zeus.test:8080"
BUCKET = "beer-sample"
SCOPE = "_default"
COLLECTION = "_default"
HEADERS = {"X-Zeus-Session": "sid-test"}


@pytest.fixture(autouse=True)
def _respx(respx_mock):
    yield


@pytest.mark.asyncio
async def test_dispatch_zeus_tool_success(http_client):
    url = f"{ZEUS_URL}/v1/{BUCKET}/{SCOPE}/{COLLECTION}/tools/find"
    route = respx.post(url).mock(return_value=httpx.Response(
        200, text='{"ok": true}', headers={"X-Zeus-Req-Id": "req-abc123"},
    ))
    status, text, used_url, req_id = await dispatch_zeus_tool(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", {"q": "beer"},
        HEADERS, corr_headers={"X-Zeus-Chat-Id": "chat-1"},
    )
    assert status == 200
    assert text == '{"ok": true}'
    assert used_url == url
    assert req_id == "req-abc123"
    sent = route.calls.last.request
    assert sent.headers["X-Zeus-Scope"] == f"{BUCKET}/{SCOPE}"
    assert sent.headers["X-Zeus-Chat-Id"] == "chat-1"
    assert json.loads(sent.content) == {"q": "beer"}


@pytest.mark.asyncio
async def test_dispatch_zeus_tool_error_status(http_client):
    url = f"{ZEUS_URL}/v1/{BUCKET}/{SCOPE}/{COLLECTION}/tools/find"
    respx.post(url).mock(return_value=httpx.Response(500, text="server error"))
    status, text, _, req_id = await dispatch_zeus_tool(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", {}, HEADERS,
    )
    assert status == 500
    assert "server error" in text
    assert req_id == ""


@pytest.mark.asyncio
async def test_dispatch_zeus_tool_http_error(http_client):
    url = f"{ZEUS_URL}/v1/{BUCKET}/{SCOPE}/{COLLECTION}/tools/find"
    respx.post(url).mock(side_effect=httpx.ReadTimeout("timed out"))
    status, text, used_url, req_id = await dispatch_zeus_tool(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", {}, HEADERS,
    )
    assert status == 0
    assert json.loads(text)["error"] == "dispatch_failed"
    assert used_url == url
    assert req_id == ""


@pytest.mark.asyncio
async def test_dispatch_zeus_tool_non_dict_args(http_client):
    url = f"{ZEUS_URL}/v1/{BUCKET}/{SCOPE}/{COLLECTION}/tools/find"
    respx.post(url).mock(return_value=httpx.Response(200, text="ok"))
    status, _, _, _ = await dispatch_zeus_tool(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", "not-a-dict", HEADERS,
    )
    assert status == 200


@pytest.mark.parametrize("verb,expected_path", [
    ("explain", "/v2/explain"),
    ("return", "/v2/return"),
])
@pytest.mark.asyncio
async def test_dispatch_v2_bare_verbs(http_client, verb, expected_path):
    url = f"{ZEUS_URL}{expected_path}"
    respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    status, _, used_url, _ = await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, verb, {}, HEADERS,
    )
    assert status == 200
    assert used_url == url


@pytest.mark.parametrize("verb", ["describe", "analyze"])
@pytest.mark.asyncio
async def test_dispatch_v2_scope_verbs(http_client, verb):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{verb}"
    route = respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    status, _, used_url, _ = await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, verb, {}, HEADERS,
    )
    assert status == 200
    assert used_url == url
    assert route.calls.last.request.headers["X-Zeus-Scope"] == f"{BUCKET}/{SCOPE}"


@pytest.mark.asyncio
async def test_dispatch_v2_pipeline(http_client):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLLECTION}/pipeline"
    route = respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    status, _, used_url, _ = await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "pipeline", {"steps": []}, HEADERS,
    )
    assert status == 200
    assert used_url == url
    assert route.calls.last.request.headers["X-Zeus-Scope"] == f"{BUCKET}/{SCOPE}"


@pytest.mark.asyncio
async def test_dispatch_v2_collection_verb(http_client):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLLECTION}/find"
    route = respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    status, _, used_url, _ = await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", {}, HEADERS,
    )
    assert status == 200
    assert used_url == url
    assert route.calls.last.request.headers["X-Zeus-Scope"] == f"{BUCKET}/{SCOPE}"


@pytest.mark.asyncio
async def test_dispatch_v2_error_and_http_error(http_client):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLLECTION}/find"
    respx.post(url).mock(return_value=httpx.Response(422, text="bad plan"))
    status, text, _, _ = await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", {}, HEADERS,
    )
    assert status == 422
    assert "bad plan" in text

    respx.post(url).mock(side_effect=httpx.ConnectError("down"))
    status, text, _, _ = await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "find", {}, HEADERS,
    )
    assert status == 0
    assert json.loads(text)["error"] == "dispatch_failed"


@pytest.mark.asyncio
async def test_dispatch_v2_corr_headers_do_not_override(http_client):
    url = f"{ZEUS_URL}/v2/explain"
    route = respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    await dispatch_zeus_v2_verb(
        ZEUS_URL, BUCKET, SCOPE, COLLECTION, "explain", {}, HEADERS,
        corr_headers={"Content-Type": "text/plain", "X-Zeus-Turn-Id": "t1"},
    )
    assert route.calls.last.request.headers["Content-Type"] == "application/json"
    assert route.calls.last.request.headers["X-Zeus-Turn-Id"] == "t1"


@pytest.mark.asyncio
async def test_dispatch_zeus_call_routes_v1(http_client):
    url = f"{ZEUS_URL}/v1/{BUCKET}/{SCOPE}/{COLLECTION}/tools/get"
    respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    status, _, used_url, _ = await dispatch_zeus_call(
        "v1", ZEUS_URL, BUCKET, SCOPE, COLLECTION, "get", {}, HEADERS,
    )
    assert status == 200
    assert "/v1/" in used_url


@pytest.mark.asyncio
async def test_dispatch_zeus_call_routes_v2(http_client):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLLECTION}/get"
    respx.post(url).mock(return_value=httpx.Response(200, text="{}"))
    status, _, used_url, _ = await dispatch_zeus_call(
        "v2", ZEUS_URL, BUCKET, SCOPE, COLLECTION, "get", {}, HEADERS,
    )
    assert status == 200
    assert "/v2/" in used_url


def test_zeus_correlation_headers_all_fields():
    h = zeus_correlation_headers("chat-1", turn_id="turn-2", call_id="call-3")
    assert h == {
        "X-Zeus-Chat-Id": "chat-1",
        "X-Zeus-Turn-Id": "turn-2",
        "X-Zeus-Call-Id": "call-3",
    }


def test_zeus_correlation_headers_mode_and_force_trace():
    h = zeus_correlation_headers(
        "c", turn_id="t", mode="analytics", force_trace=True,
    )
    assert h["X-Zeus-Mode"] == "analytics"
    assert h["X-Zeus-Trace"] == "1"
    assert h["X-Zeus-Chat-Id"] == "c"


def test_zeus_correlation_headers_partial():
    assert zeus_correlation_headers("") == {}
    assert zeus_correlation_headers("c", turn_id="") == {"X-Zeus-Chat-Id": "c"}
    assert zeus_correlation_headers("", call_id="x") == {"X-Zeus-Call-Id": "x"}


def test_apply_zeus_mode_and_force_trace_helpers():
    from zeus_client.zeus.dispatch import (
        apply_zeus_force_trace_header,
        apply_zeus_mode_header,
    )

    h = apply_zeus_mode_header({}, "analytics")
    assert h["X-Zeus-Mode"] == "analytics"
    # does not override existing
    h2 = apply_zeus_mode_header({"X-Zeus-Mode": "research"}, "analytics")
    assert h2["X-Zeus-Mode"] == "research"
    h3 = apply_zeus_force_trace_header(h, True)
    assert h3["X-Zeus-Trace"] == "1"
    h4 = apply_zeus_force_trace_header(h, False)
    assert "X-Zeus-Trace" not in h4