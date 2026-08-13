"""Tests for python3/agent/session_phase.py — session create/rehydrate/commit."""

import json

import httpx
import pytest
import respx
from zeus_client.agent.session_phase import commit_session_turn, setup_contract_and_session

ZEUS_URL = "http://zeus.test:8080"
BUCKET = "beer-sample"
SCOPE = "_default"
HEADERS = {"X-Zeus-Session": "auth-sid"}


@pytest.fixture(autouse=True)
def _respx(respx_mock):
    yield


def _trace():
    return {"notes": [], "steps": [], "spans": [], "tool_calls": []}


def _chat_req(stamped=None):
    msg = {"role": "system", "content": "system rules"}
    req = {"messages": [msg], "tools": []}
    if stamped:
        req["_contract_hash"] = stamped
    return req


@pytest.mark.asyncio
async def test_sessions_disabled_no_contract(monkeypatch):
    zcfg = {"enable_durable_sessions": False}
    trace = _trace()
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["enable_sessions"] is False
    assert any("contract: none" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_sessions_disabled(monkeypatch):
    zcfg = {
        "enable_durable_sessions": False,
        "scope_contracts": {
            f"{BUCKET}/{SCOPE}": {"contract_id": "cid-1", "contract_hash": "md5:abc"},
        },
    }
    trace = _trace()
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "md5:computed",
        "md5:stamped",
        HEADERS,
    )
    assert result["enable_sessions"] is False
    assert result["sid"] == ""
    assert any("durable sessions: disabled" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_matching_stamped_hash_no_warning(http_client, monkeypatch):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {
            f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:same"}
        },
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sess-match", "round": 1, "contract_status": "match"},
        )
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.extract_stamped_hash",
        lambda _r: "md5:same",
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.compute_contract_hash",
        lambda _r: "md5:same",
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "md5:same",
        "md5:same",
        HEADERS,
    )
    assert result["sid"] == "sess-match"
    assert not any("WARNING: embedded stamped hash" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_bound_hash_differs_from_loaded(http_client, monkeypatch):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {
            f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:bound"}
        },
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sess-diff", "round": 1, "contract_status": "match"},
        )
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.extract_stamped_hash",
        lambda _r: "md5:loaded",
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.compute_contract_hash",
        lambda _r: "md5:loaded",
    )
    await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "md5:loaded",
        "md5:loaded",
        HEADERS,
    )
    assert any("bound contract_hash differs" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_new_session_create_success(http_client, monkeypatch):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sess-new-123", "round": 1, "contract_status": "match"},
            headers={"X-Zeus-Req-Id": "creq-ok"},
        )
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.extract_stamped_hash",
        lambda _r: "md5:stamped",
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.compute_contract_hash",
        lambda _r: "md5:computed",
    )

    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req("md5:stamped"),
        "hello",
        "",
        0,
        trace,
        "md5:computed",
        "md5:stamped",
        HEADERS,
    )
    assert result["sid"] == "sess-new-123"
    assert result["this_user_round"] == 1
    assert result["contract_hash"] == "md5:computed"
    assert result["bound_contract_hash"] == "md5:h"
    assert trace["session"]["created"] is True
    assert trace["session"]["contract_status"] == "match"
    assert any("WARNING: embedded stamped hash" in n for n in trace["notes"])
    assert any("using payload hash on session APIs" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_new_session_create_failure_409_regex_exception(http_client, monkeypatch):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            409,
            text='{"error":"payload_hash","payload_hash":"md5:zeus"}',
            headers={"X-Zeus-Req-Id": "creq-x"},
        )
    )

    import re as re_mod

    real_search = re_mod.search

    def boom(pattern, text, *a, **k):
        if "payload_hash" in pattern:
            raise RuntimeError("regex broke")
        return real_search(pattern, text, *a, **k)

    monkeypatch.setattr(re_mod, "search", boom)
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == ""


@pytest.mark.asyncio
async def test_new_session_create_failure_409_payload_hash_no_regex_match(http_client):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            409,
            text='{"error":"payload_hash missing md5 form"}',
            headers={"X-Zeus-Req-Id": "creq-nomatch"},
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == ""
    assert not any("Zeus computed payload_hash" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_new_session_create_failure_409_without_payload_hash(http_client):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            409,
            text='{"error":"conflict"}',
            headers={"X-Zeus-Req-Id": "creq-409"},
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == ""
    assert not any("Zeus computed payload_hash" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_new_session_create_failure_409_extracts_payload_hash(http_client):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    err_body = '{"error":"conflict","payload_hash":"md5:zeus-extracted"}'
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            409,
            text=err_body,
            headers={"X-Zeus-Req-Id": "creq-extract"},
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == ""
    assert any("md5:zeus-extracted" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_new_session_create_failure_with_409_payload_hash(http_client):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    err_body = '{"error":"conflict","payload_hash":"md5:zeus-computed"}'
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            409,
            text=err_body,
            headers={"X-Zeus-Req-Id": "creq-fail"},
        )
    )

    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hello",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == ""
    assert trace["session"]["created"] is False
    assert trace.get("session_error")
    assert any("payload_hash" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_no_contract_id_session_still_created(http_client):
    zcfg = {"enable_durable_sessions": True}
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            200,
            json={"session_id": "sess-no-contract", "round": 1, "contract_status": "none"},
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "auto",
        _chat_req(),
        "hi",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["contract_id"] == ""
    assert any("contract: none" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_hash_compute_exception_non_fatal(monkeypatch, http_client):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "h"}},
    }
    trace = _trace()
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            200,
            json={"session_id": "s1", "round": 1, "contract_status": "match"},
        )
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.extract_stamped_hash",
        lambda _r: (_ for _ in ()).throw(RuntimeError("hash fail")),
    )

    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "auto",
        _chat_req(),
        "hi",
        "",
        0,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == "s1"
    assert any("hash_compute_failed" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_rehydrate_existing_session_success(http_client, monkeypatch):
    zcfg = {"enable_durable_sessions": True}
    trace = _trace()
    sid = "existing-sid-99"
    respx.get(f"{ZEUS_URL}/v2/session/{sid}?rounds=6").mock(
        return_value=httpx.Response(
            200,
            json={"round": 2, "conversation": [{"role": "user"}, {"role": "assistant"}]},
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "auto",
        _chat_req(),
        "follow-up",
        sid,
        2,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == sid
    assert result["this_user_round"] == 3
    assert trace["session_rehydrate"]["server_round"] == 2
    assert trace["session"]["rehydrated"] is True
    assert trace["session"]["created"] is False
    assert trace["session"]["contract_status"] == "none"
    assert any("contract_status=none" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_rehydrate_existing_session_with_contract_match(http_client, monkeypatch):
    zcfg = {"enable_durable_sessions": True}
    sid = "sess-rehydrate-match"
    trace = _trace()
    respx.get(f"{ZEUS_URL}/v2/session/{sid}?rounds=6").mock(
        return_value=httpx.Response(
            200,
            json={
                "session_id": sid,
                "round": 5,
                "hash": "md5:abc123",
                "contract_id": "analytics_v4",
                "conversation": [{"role": "user"}] * 10,
                "rounds_loaded": 5,
            },
        )
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.resolve_contract_for_scope",
        lambda *a, **k: ("analytics_v4", "md5:abc123"),
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.extract_stamped_hash",
        lambda _r: "md5:abc123",
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.compute_contract_hash",
        lambda _r: "md5:abc123",
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req("md5:abc123"),
        "next",
        sid,
        5,
        trace,
        "md5:abc123",
        "md5:abc123",
        HEADERS,
    )
    assert result["sid"] == sid
    assert result["this_user_round"] == 6
    assert result["contract_id"] == "analytics_v4"
    assert result["contract_hash"] == "md5:abc123"
    assert trace["session"]["contract_status"] == "match"
    assert trace["session"]["rehydrated"] is True
    assert trace["session_rehydrate"]["contract_status"] == "match"
    assert any("contract_status=match" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_rehydrate_existing_session_with_contract_drift(http_client, monkeypatch):
    zcfg = {"enable_durable_sessions": True}
    sid = "sess-rehydrate-drift"
    trace = _trace()
    respx.get(f"{ZEUS_URL}/v2/session/{sid}?rounds=6").mock(
        return_value=httpx.Response(
            200,
            json={
                "session_id": sid,
                "round": 2,
                "hash": "md5:old-hash",
                "contract_id": "analytics_v4",
                "conversation": [{"role": "user"}, {"role": "assistant"}],
            },
        )
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.resolve_contract_for_scope",
        lambda *a, **k: ("analytics_v4", "md5:new-hash"),
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.extract_stamped_hash",
        lambda _r: "md5:new-hash",
    )
    monkeypatch.setattr(
        "zeus_client.agent.session_phase.compute_contract_hash",
        lambda _r: "md5:new-hash",
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req("md5:new-hash"),
        "next",
        sid,
        2,
        trace,
        "md5:new-hash",
        "md5:new-hash",
        HEADERS,
    )
    assert result["sid"] == sid
    assert trace["session"]["contract_status"] == "drift"
    assert any("contract_status=drift" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_rehydrate_failure_creates_fresh_session(http_client):
    zcfg = {
        "enable_durable_sessions": True,
        "scope_contracts": {f"{BUCKET}/{SCOPE}": {"contract_id": "cid", "contract_hash": "md5:h"}},
    }
    trace = _trace()
    dead = "stale-sid"
    respx.get(f"{ZEUS_URL}/v2/session/{dead}?rounds=6").mock(return_value=httpx.Response(404))
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            201,
            json={"session_id": "sess-recovered", "round": 1, "contract_status": "match"},
            headers={"X-Zeus-Req-Id": "creq-recover"},
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "analytics",
        _chat_req(),
        "hi",
        dead,
        6,
        trace,
        "md5:h",
        "md5:h",
        HEADERS,
    )
    assert result["sid"] == "sess-recovered"
    assert result["this_user_round"] == 1
    assert trace["session"]["created"] is True
    assert trace["session"]["contract_status"] == "match"
    assert trace["session"]["recovered_from"] == dead
    assert trace["session_rehydrate"]["failed"] is True
    assert trace["session_rehydrate"]["recreated"] is True
    assert any("rehydrate" in n and "failed" in n for n in trace["notes"])
    assert any("creating fresh session" in n for n in trace["notes"])
    assert any("session create sess-recover" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_rehydrate_failure_and_create_failure_clears_sid(http_client):
    zcfg = {"enable_durable_sessions": True}
    trace = _trace()
    dead = "stale-sid-2"
    respx.get(f"{ZEUS_URL}/v2/session/{dead}?rounds=6").mock(return_value=httpx.Response(404))
    respx.post(f"{ZEUS_URL}/v2/session").mock(
        return_value=httpx.Response(
            409,
            text='{"error":"contract_required"}',
        )
    )
    result = await setup_contract_and_session(
        ZEUS_URL,
        zcfg,
        BUCKET,
        SCOPE,
        "auto",
        _chat_req(),
        "hi",
        dead,
        1,
        trace,
        "",
        "",
        HEADERS,
    )
    assert result["sid"] == ""
    assert result["this_user_round"] == 1
    assert trace["session"]["created"] is False
    assert trace["session"]["recovered_from"] == dead
    assert any("rehydrate" in n and "failed" in n for n in trace["notes"])
    assert any("session create failed" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_commit_session_turn_disabled():
    trace = _trace()
    meta = await commit_session_turn(
        ZEUS_URL,
        "",
        False,
        1,
        "",
        "",
        {},
        [],
        [],
        [],
        trace,
        HEADERS,
    )
    assert meta["enabled"] is False
    assert "session" not in trace or trace.get("session") is not None


@pytest.mark.asyncio
async def test_commit_just_created_session(http_client):
    trace = {
        "notes": [],
        "session": {"created": True, "contract_status": "match"},
    }
    sid = "sess-commit"
    respx.post(f"{ZEUS_URL}/v2/session/trace").mock(return_value=httpx.Response(200, json={}))
    turn_route = respx.post(f"{ZEUS_URL}/v2/session/{sid}/turn").mock(
        return_value=httpx.Response(200, json={"round": 2}, headers={"X-Zeus-Req-Id": "turn-req"}),
    )
    delta = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]
    meta = await commit_session_turn(
        ZEUS_URL,
        sid,
        True,
        1,
        "cid",
        "hash",
        {"tools": []},
        delta,
        [],
        [("req-1", "find", 200, "ok", "http://z/find")],
        trace,
        HEADERS,
    )
    assert meta["round"] == 2
    assert meta["primary_req_id"] == "req-1"
    assert any("trace req-1" in n for n in trace["notes"])
    payload = json.loads(turn_route.calls.last.request.content)
    assert payload["round"] == 2
    assert payload["new_turns"] == [{"role": "assistant", "content": "a"}]


@pytest.mark.asyncio
async def test_commit_multi_hop_aggregate_payload(http_client):
    """All hops get the same rich body; primary (error) is last POST."""
    trace = {
        "notes": [],
        "session": {"created": False, "contract_status": "match"},
        "steps": [
            {
                "type": "return_result",
                "args": {
                    "summary": "done",
                    "query_decomposition": {"intent": "List", "entity": "Business"},
                    "decomposition": {"targets": ["Business"]},
                    "confidence": "high",
                },
            }
        ],
    }
    sid = "sess-multi"
    route = respx.post(f"{ZEUS_URL}/v2/session/trace").mock(
        return_value=httpx.Response(201, json={"contract_status": "match"}),
    )
    respx.post(f"{ZEUS_URL}/v2/session/{sid}/turn").mock(
        return_value=httpx.Response(200, json={"round": 1}),
    )
    hops = [
        {
            "req_id": "req-pipe",
            "name": "pipeline",
            "status": 200,
            "snippet": '{"status":"ok"}',
            "url": "http://z/pipeline",
            "ms": 23,
            "step_costs": [{"as": "tampa", "status": "ok", "result_size": 0}],
        },
        {
            "req_id": "req-search",
            "name": "search",
            "status": 500,
            "snippet": "search_timeout",
            "url": "http://z/search",
            "ms": 2000,
        },
    ]
    meta = await commit_session_turn(
        ZEUS_URL,
        sid,
        True,
        1,
        "cid",
        "hash",
        {"tools": []},
        [{"role": "assistant", "content": "done"}],
        [],
        hops,
        trace,
        HEADERS,
    )
    assert meta["req_ids"] == ["req-pipe", "req-search"]
    assert meta["primary_req_id"] == "req-search"
    assert meta["preferred_req_id"] == "req-search"
    assert route.call_count == 2
    # Last post is primary (error search)
    last = json.loads(route.calls.last.request.content)
    assert last["req_id"] == "req-search"
    assert last["outcome"] == "error"
    assert last["zeus_response"]["aggregate"] is True
    assert last["zeus_response"]["req_ids"] == ["req-pipe", "req-search"]
    assert last["zeus_response"]["primary_req_id"] == "req-search"
    assert last["zeus_response"]["layer_a"]["intent"] == "List"
    assert last["zeus_response"]["layer_a"]["confidence"] == "high"
    assert len(last["turns"]) == 2
    assert any("result_size=0" in t["content"] for t in last["turns"])
    # Both posts carry identical multi-hop body
    first = json.loads(route.calls[0].request.content)
    assert first["zeus_response"]["tool_hops"] == last["zeus_response"]["tool_hops"]
    assert first["zeus_response"]["layer_a"] == last["zeus_response"]["layer_a"]
    assert first["req_id"] == "req-pipe"
    assert trace["session"]["preferred_req_id"] == "req-search"
    assert any("aggregate=1" in n for n in trace["notes"])
    assert any("layer_a=1" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_commit_existing_session_turn(http_client):
    trace = {"notes": [], "session": {"created": False, "contract_status": "match"}}
    sid = "sess-existing"
    respx.post(f"{ZEUS_URL}/v2/session/trace").mock(
        return_value=httpx.Response(500, text="trace-fail")
    )
    respx.post(f"{ZEUS_URL}/v2/session/{sid}/turn").mock(
        return_value=httpx.Response(400, text="bad")
    )
    meta = await commit_session_turn(
        ZEUS_URL,
        sid,
        True,
        3,
        "cid",
        "hash",
        {},
        [{"role": "assistant", "content": "x"}],
        [{"role": "user"}],
        [("req-x", "get", 500, "err", "http://z")],
        trace,
        HEADERS,
    )
    assert meta["round"] == 3
    assert trace.get("session_error")
    assert any("trace post" in n for n in trace["notes"])
    assert any("turn post" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_commit_skips_empty_req_id(http_client):
    trace = {"notes": [], "session": {"created": False, "contract_status": "match"}}
    sid = "sess-skip-rid"
    respx.post(f"{ZEUS_URL}/v2/session/trace").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{ZEUS_URL}/v2/session/{sid}/turn").mock(return_value=httpx.Response(200, json={}))
    meta = await commit_session_turn(
        ZEUS_URL,
        sid,
        True,
        1,
        "cid",
        "hash",
        {},
        [{"role": "assistant", "content": "x"}],
        [],
        [("", "find", 200, "ok", "http://z/find"), ("req-ok", "get", 200, "ok", "http://z/get")],
        trace,
        HEADERS,
    )
    assert meta["req_ids"] == ["req-ok"]
    assert any("trace req-ok" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_commit_no_turns_to_persist(http_client):
    trace = {"notes": [], "session": {"created": False, "contract_status": "none"}}
    sid = "sess-empty"
    meta = await commit_session_turn(
        ZEUS_URL,
        sid,
        True,
        1,
        "",
        "",
        {},
        [],
        [],
        [],
        trace,
        HEADERS,
    )
    assert any("no new turns to persist" in n for n in trace["notes"])
    assert meta["session_id"] == sid
