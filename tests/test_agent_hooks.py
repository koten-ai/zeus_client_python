"""Tests for agent hook surface — migrated from tools/test_hooks_fire.py."""
import pytest

import zeus_client.agent.tool_round as tr
from zeus_client.agent.hooks import AgentDecision, AgentHooks


class RecordingHooks(AgentHooks):
    def __init__(self):
        self.events = []
        self.calls = []

    async def observe(self, event, data):
        self.events.append(event)

    async def on_round_start(self, round_num, ctx):
        self.calls.append("on_round_start")
        return AgentDecision(inject_messages=[
            {"role": "system", "content": "User profile: loyalty_tier=Gold."},
        ])

    async def on_ai_response(self, response, ctx):
        self.calls.append("on_ai_response")
        return None

    async def before_zeus_dispatch(self, name, args, ctx):
        self.calls.append("before_zeus_dispatch")
        args["_injected_filter"] = True
        return args

    async def after_zeus_dispatch(self, name, args, status, result_text, ctx):
        self.calls.append("after_zeus_dispatch")
        return result_text.replace("RAW", "GUARDED")

    async def should_continue(self, round_num, messages, ctx):
        self.calls.append("should_continue")
        return True


async def _fake_llm(base_url, api_key, payload, extra_headers=None):
    return 200, {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "find", "arguments": '{"entity_type":"Beer"}'},
                }],
            },
        }],
        "usage": {"total_tokens": 5},
    }


async def _fake_dispatch(api_version, zeus_url, bucket, scope, collection, name, args,
                       zeus_headers, corr_headers=None):
    return 200, '{"rows": "RAW data"}', "http://zeus/find", "req-1"


def _make_trace():
    return {
        "steps": [], "spans": [], "ai_requests": [], "ai_responses": [],
        "tool_calls": [], "notes": [], "session": {"contract_status": "match"},
    }


@pytest.fixture
def patched_tool_round(monkeypatch):
    monkeypatch.setattr(tr, "llm_chat_payload", _fake_llm)
    monkeypatch.setattr(tr, "dispatch_zeus_call", _fake_dispatch)


@pytest.mark.asyncio
async def test_hooks_fire_through_tool_round(patched_tool_round):
    hooks = RecordingHooks()
    ctx = {"bucket": "beer-sample", "scope": "_default"}
    trace = _make_trace()
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "find beers"},
    ]

    answer, should_break, msg = await tr.run_llm_round(
        1, "grok-test", messages, [], None, None,
        "http://llm", "key", hooks, ctx, trace, lambda: 0,
    )
    assert not should_break and msg is not None
    assert any("loyalty_tier=Gold" in (m.get("content") or "") for m in messages)
    messages.append(msg)

    answer, should_break, _, outcome = await tr.execute_tool_calls(
        1, msg.get("tool_calls") or [], messages,
        "v2", "http://zeus", "beer-sample", "_default", None,
        {}, {}, hooks, ctx, trace, lambda: 0, "turn-1", "conv-1", False, [],
    )
    assert outcome.tools_executed == 1

    rec = trace["tool_calls"][0]
    assert rec["args"].get("_injected_filter") is True
    assert "GUARDED" in rec["result_text"]
    assert await hooks.should_continue(1, messages, ctx) is True

    for ev in ("round_start", "ai_response", "tool_call_planned", "zeus_result"):
        assert ev in hooks.events, f"missing observe event {ev!r}"

    for cb in ("on_round_start", "on_ai_response", "before_zeus_dispatch",
               "after_zeus_dispatch", "should_continue"):
        assert cb in hooks.calls, f"missing hook call {cb!r}"


@pytest.mark.asyncio
async def test_default_hooks_are_no_ops():
    hooks = AgentHooks()
    assert await hooks.observe("x", {}) is None
    assert await hooks.before_zeus_dispatch("find", {}, {}) == {}
    assert await hooks.after_zeus_dispatch("find", {}, 200, "ok", {}) == "ok"
    assert await hooks.on_ai_response({}, {}) is None
    assert await hooks.on_round_start(1, {}) is None
    assert await hooks.should_continue(1, [], {}) is True