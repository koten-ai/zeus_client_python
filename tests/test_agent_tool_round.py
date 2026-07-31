"""Additional branch coverage for python3/agent/tool_round.py."""
import json

import httpx
import pytest

import zeus_client.agent.tool_round as tr
from zeus_client.agent.hooks import AgentDecision, AgentHooks


def _trace():
    return {
        "steps": [], "spans": [], "ai_requests": [], "ai_responses": [],
        "tool_calls": [], "notes": [],
    }


@pytest.mark.asyncio
async def test_round_start_stop_with_force_return(monkeypatch):
    class StopHooks(AgentHooks):
        async def on_round_start(self, round_num, ctx):
            return AgentDecision(stop=True, reason="budget", force_return="done early")

    async def fake_llm(*_a, **_k):
        return 200, {}

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    trace = _trace()
    answer, should_break, msg = await tr.run_llm_round(
        1, "m", [], [], None, None, "http://llm", "k", StopHooks(), {}, trace, lambda: 0,
    )
    assert should_break is True
    assert answer == "done early"
    assert msg is None
    assert "stopped by hook" in trace["notes"][-1]


@pytest.mark.asyncio
async def test_round_start_inject_only(monkeypatch):
    class InjectHooks(AgentHooks):
        async def on_round_start(self, round_num, ctx):
            return AgentDecision(inject_messages=[{"role": "system", "content": "injected"}])

    async def fake_llm(*_a, **_k):
        return 200, {
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}],
        }

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    messages = []
    trace = _trace()
    answer, should_break, msg = await tr.run_llm_round(
        1, "m", messages, [], None, None, "http://llm", "k", InjectHooks(), {}, trace, lambda: 0,
    )
    assert any(m.get("content") == "injected" for m in messages)
    assert "hook injected" in trace["notes"][-1]
    assert answer == "hi"
    assert should_break is True


@pytest.mark.asyncio
async def test_on_ai_response_stop(monkeypatch):
    class AiStopHooks(AgentHooks):
        async def on_ai_response(self, response, ctx):
            return AgentDecision(stop=True, reason="policy", force_return="blocked")

    async def fake_llm(*_a, **_k):
        return 200, {"choices": [{"message": {"content": "secret"}}]}

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    answer, should_break, msg = await tr.run_llm_round(
        1, "m", [], [], None, None, "http://llm", "k", AiStopHooks(), {}, _trace(), lambda: 0,
    )
    assert answer == "blocked"
    assert should_break is True


@pytest.mark.asyncio
async def test_llm_http_error(monkeypatch):
    async def fake_llm(*_a, **_k):
        return 502, "bad gateway"

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    answer, should_break, msg = await tr.run_llm_round(
        1, "m", [], [], None, None, "http://llm", "k", AgentHooks(), {}, _trace(), lambda: 0,
    )
    assert should_break is True
    assert "HTTP 502" in answer


@pytest.mark.asyncio
async def test_llm_non_dict_response(monkeypatch):
    async def fake_llm(*_a, **_k):
        return 200, "not-a-dict"

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    answer, should_break, _ = await tr.run_llm_round(
        1, "m", [], [], None, None, "http://llm", "k", AgentHooks(), {}, _trace(), lambda: 0,
    )
    assert should_break is True
    assert "HTTP 200" in answer


@pytest.mark.asyncio
async def test_no_tool_calls_returns_content(monkeypatch):
    async def fake_llm(*_a, **_k):
        return 200, {
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "final answer"},
            }],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    messages = []
    answer, should_break, msg = await tr.run_llm_round(
        1, "m", messages, [], None, None, "http://llm", "k", AgentHooks(), {}, _trace(), lambda: 0,
    )
    assert answer == "final answer"
    assert should_break is True
    assert messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_no_content_fallback(monkeypatch):
    async def fake_llm(*_a, **_k):
        return 200, {"choices": [{"finish_reason": "stop", "message": {}}]}

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    answer, should_break, _ = await tr.run_llm_round(
        1, "m", [], [], None, None, "http://llm", "k", AgentHooks(), {}, _trace(), lambda: 0,
    )
    assert answer == "(model returned no content)"


@pytest.mark.asyncio

@pytest.mark.asyncio
async def test_return_result_tool_ends_turn(monkeypatch):
    async def fake_dispatch(*_a, **_k):
        pytest.fail("dispatch should not run for return_result")

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{
        "id": "c1",
        "function": {"name": "return_result", "arguments": json.dumps({"summary": "The answer"})},
    }]
    messages = []
    trace = _trace()
    answer, should_break, _, outcome = await tr.execute_tool_calls(
        1, tool_calls, messages, "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, trace, lambda: 0, "t1", "conv", False, [],
    )
    assert answer == "The answer"
    assert should_break is True
    assert outcome.return_seen is True
    assert outcome.terminal_summary == "The answer"
    # Assistant is deferred to the loop (cheap vs insight)
    assert not any(m.get("role") == "assistant" for m in messages)
    assert messages[-1]["role"] == "tool"


@pytest.mark.asyncio
async def test_pipeline_turn_complete_is_return_seen(monkeypatch):
    body = json.dumps({
        "turn_complete": True,
        "summary": "pipeline done",
        "data": {"rows": [{"name": "A"}]},
    })

    async def fake_dispatch(*_a, **_k):
        return 200, body, "http://z/pipeline", "req-p"

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{
        "id": "c1",
        "function": {
            "name": "pipeline",
            "arguments": json.dumps({"steps": [{"as": "x", "verb": "find"}]}),
        },
    }]
    messages = []
    answer, should_break, _, outcome = await tr.execute_tool_calls(
        1, tool_calls, messages, "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, _trace(), lambda: 0, "t1", "conv", False, [],
    )
    assert should_break is True
    assert outcome.return_seen is True
    assert outcome.terminal_summary == "pipeline done"
    assert outcome.tools_with_data == 1
    assert answer == "pipeline done"


@pytest.mark.asyncio
async def test_pipeline_args_summary_captured_without_turn_complete(monkeypatch):
    body = json.dumps({
        "status": "failed",
        "error": "project failed",
        "results_so_far": {"reno_biz": {"rows": [{"name": "A"}]}},
    })

    async def fake_dispatch(*_a, **_k):
        return 200, body, "http://z/pipeline", "req-p"

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{
        "id": "c1",
        "function": {
            "name": "pipeline",
            "arguments": json.dumps({
                "summary": "Businesses in Reno ranked by review count",
                "steps": [{"as": "x", "verb": "find"}],
            }),
        },
    }]
    messages = []
    answer, should_break, _, outcome = await tr.execute_tool_calls(
        1, tool_calls, messages, "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, _trace(), lambda: 0, "t1", "conv", False, [],
    )
    assert should_break is False
    assert outcome.return_seen is False
    assert outcome.tools_with_data == 1
    assert outcome.tool_arg_summary == "Businesses in Reno ranked by review count"
    assert answer is None


@pytest.mark.asyncio
async def test_force_final_llm_answer_no_tools(monkeypatch):
    captured = {}

    async def fake_llm(_url, _key, payload, extra_headers=None):
        captured["payload"] = payload
        return 200, {
            "choices": [{"message": {"role": "assistant", "content": "narrated"}}],
        }

    monkeypatch.setattr(tr, "llm_chat_payload", fake_llm)
    messages = [{"role": "user", "content": "q"}]
    out = await tr.force_final_llm_answer(
        1, "m", messages, None, None, "http://llm", "k",
        AgentHooks(), {}, _trace(), lambda: 0,
        instruction=tr.INSIGHT_AFTER_ZEUS_INSTRUCTION,
        cause="test",
    )
    assert out == "narrated"
    assert "tools" not in captured["payload"]
    assert messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_invalid_tool_args_json(monkeypatch):
    async def fake_dispatch(*_a, **_k):
        return 200, "{}", "http://z/find", "req-1"

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{"id": "c1", "function": {"name": "find", "arguments": "not-json"}}]
    messages = []
    trace = _trace()
    _, should_break, _, outcome = await tr.execute_tool_calls(
        1, tool_calls, messages, "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, trace, lambda: 0, "t1", "conv", False, [],
    )
    assert should_break is False
    assert trace["tool_calls"][0]["args"] == {}
    assert outcome.tools_executed == 1


@pytest.mark.asyncio
async def test_basic_auth_401_retry_success(monkeypatch, reset_auth_cache, http_client):
    calls = []

    async def flaky_dispatch(api_version, zeus_url, bucket, scope, collection, name, args,
                             zeus_headers, corr_headers=None):
        calls.append(zeus_headers.get("X-Zeus-Session", ""))
        if len(calls) == 1:
            return 401, "unauthorized", "http://z/find", ""
        return 200, '{"ok": true}', "http://z/find", "req-2"

    async def remint(*_a, **_k):
        return {"X-Zeus-Session": "sid-new"}, "re-minted"

    monkeypatch.setattr(tr, "dispatch_zeus_call", flaky_dispatch)
    monkeypatch.setattr(tr, "resolve_zeus_auth", remint)

    tool_calls = [{"id": "c1", "function": {"name": "find", "arguments": "{}"}}]
    trace = _trace()
    zcfg = {"auth_mode": "basic"}
    _, should_break, headers, _ = await tr.execute_tool_calls(
        1, tool_calls, [], "v2", "http://z", "b", "s", "c",
        zcfg, {"X-Zeus-Session": "sid-old"}, AgentHooks(), {}, trace, lambda: 0,
        "t1", "conv", False, [],
    )
    assert should_break is False
    assert headers["X-Zeus-Session"] == "sid-new"
    assert any("re-minted after 401" in n for n in trace["notes"])
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_basic_auth_401_remint_failure(monkeypatch):
    async def dispatch_401(*_a, **_k):
        return 401, "unauthorized", "http://z/find", ""

    async def remint_fail(*_a, **_k):
        raise RuntimeError("login down")

    monkeypatch.setattr(tr, "dispatch_zeus_call", dispatch_401)
    monkeypatch.setattr(tr, "resolve_zeus_auth", remint_fail)

    tool_calls = [{"id": "c1", "function": {"name": "find", "arguments": "{}"}}]
    trace = _trace()
    _, _, _, _ = await tr.execute_tool_calls(
        1, tool_calls, [], "v2", "http://z", "b", "s", "c",
        {"auth_mode": "basic"}, {}, AgentHooks(), {}, trace, lambda: 0,
        "t1", "conv", False, [],
    )
    assert any("re-mint after 401 failed" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_pipeline_step_spans(monkeypatch):
    pipeline_result = json.dumps({
        "meta": {"step_costs": [{"as": "s1", "ms": 10, "verb": "find"}]},
    })

    async def fake_dispatch(*_a, **_k):
        return 200, pipeline_result, "http://z/pipeline", "req-p"

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{
        "id": "c1",
        "function": {
            "name": "pipeline",
            "arguments": json.dumps({"steps": [{"name": "s1", "verb": "find"}]}),
        },
    }]
    trace = _trace()
    await tr.execute_tool_calls(
        1, tool_calls, [], "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, trace, lambda: 0, "t1", "conv", False, [],
    )
    assert any(s.get("name", "").startswith("pipeline.") for s in trace["spans"])


@pytest.mark.asyncio
async def test_toon_and_req_id_tracking(monkeypatch):
    async def fake_dispatch(*_a, **_k):
        return 200, '{"rows":[]}', "http://z/find", "req-track"

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{"id": "c1", "function": {"name": "find", "arguments": "{}"}}]
    trace = _trace()
    this_turn_reqs = []
    await tr.execute_tool_calls(
        1, tool_calls, [], "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, trace, lambda: 0, "t1", "conv-9", True, this_turn_reqs,
    )
    assert trace["tool_calls"][0]["ai_content_format"] == "toon"
    assert this_turn_reqs == [("req-track", "find", 200, '{"rows":[]}', "http://z/find")]


@pytest.mark.asyncio
async def test_non_json_tool_result(monkeypatch):
    async def fake_dispatch(*_a, **_k):
        return 200, "plain-text-result", "http://z/find", ""

    monkeypatch.setattr(tr, "dispatch_zeus_call", fake_dispatch)
    tool_calls = [{"id": "c1", "function": {"name": "find", "arguments": "{}"}}]
    trace = _trace()
    await tr.execute_tool_calls(
        1, tool_calls, [], "v2", "http://z", "b", "s", "c",
        {}, {}, AgentHooks(), {}, trace, lambda: 0, "t1", "conv", False, [],
    )
    assert trace["tool_calls"][0]["result_json"] is None
