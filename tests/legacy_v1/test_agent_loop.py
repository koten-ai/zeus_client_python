"""Tests for python3/agent/loop.py — agent turn orchestration."""

import pytest
import zeus_client.agent.loop as loop_mod
from zeus_client.agent.hooks import AgentHooks
from zeus_client.agent.tool_round import ToolRoundOutcome
from zeus_client.constants import MAX_ROUNDS


def _empty_outcome(**kwargs):
    return ToolRoundOutcome(**kwargs)


def _minimal_chat_req():
    return {
        "messages": [{"role": "system", "content": "You are helpful."}],
        "tools": [{"type": "function", "function": {"name": "find", "parameters": {}}}],
    }


@pytest.fixture
def patched_loop(monkeypatch):
    async def fake_auth(*_a, **_k):
        return {"X-Zeus-Session": "sid"}, "test auth"

    async def fake_catalog(*_a, **_k):
        return _minimal_chat_req(), "local file"

    async def fake_session_setup(*_a, **_k):
        return {
            "sid": "sess-loop",
            "turn_id": "turn_test",
            "this_user_round": 1,
            "contract_id": "cid",
            "contract_hash": "md5:hash",
            "enable_sessions": False,
            "stamped_h": "",
            "current_content_h": "",
        }

    async def fake_commit(*_a, **_k):
        return {
            "session_id": "sess-loop",
            "round": 1,
            "contract_id": "cid",
            "contract_hash": "md5:hash",
            "contract_status": "none",
            "req_ids": [],
            "enabled": False,
        }

    monkeypatch.setattr(loop_mod, "resolve_zeus_auth", fake_auth)
    monkeypatch.setattr(loop_mod, "load_chat_request", fake_catalog)
    monkeypatch.setattr(loop_mod, "setup_contract_and_session", fake_session_setup)
    monkeypatch.setattr(loop_mod, "commit_session_turn", fake_commit)
    monkeypatch.setattr(loop_mod, "extract_stamped_hash", lambda _r: "")
    monkeypatch.setattr(loop_mod, "compute_contract_hash", lambda _r: "md5:computed")
    monkeypatch.setattr(loop_mod, "cache_hints", lambda *_a: ({}, {}))
    return monkeypatch


@pytest.mark.asyncio
async def test_setup_turn_context(patched_loop):
    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {"auth_mode": "none"},
        "v2",
        "analytics",
        "beer-sample",
        "_default",
        "hello",
        [],
        False,
        "grok",
        "https://api.x.ai/v1",
        "conv-1",
    )
    assert tc.messages[-1]["content"] == "hello"
    assert tc.trace["api_version"] == "v2"
    assert any("auth:" in n for n in tc.trace["notes"])
    assert any("chat_request:" in n for n in tc.trace["notes"])
    assert any("optimized: off" in n for n in tc.trace["notes"])
    assert isinstance(tc.ctx["_at_ms"](), int)


@pytest.mark.asyncio
async def test_setup_turn_context_standardized_shape_note(patched_loop, monkeypatch):
    req = _minimal_chat_req()
    req["_format"] = "zeus.chat_request.v2"

    async def fake_catalog(*_a, **_k):
        return req, "local"

    monkeypatch.setattr(loop_mod, "load_chat_request", fake_catalog)
    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v2",
        "auto",
        "b",
        "s",
        "q",
        [],
        False,
        "grok",
        "http://llm",
        None,
    )
    assert any("catalog shape: new standardized" in n for n in tc.trace["notes"])


@pytest.mark.asyncio
async def test_setup_turn_context_business_logic_and_toon(patched_loop, monkeypatch):
    req = _minimal_chat_req()
    req["guidance"] = {"injections": {"business_logic": ["rule one"]}}

    async def fake_catalog(*_a, **_k):
        return req, "local"

    monkeypatch.setattr(loop_mod, "load_chat_request", fake_catalog)
    monkeypatch.setattr(loop_mod, "apply_injected_business_logic", lambda r: r)
    monkeypatch.setattr(loop_mod, "_toon_encode", lambda x: "toon:" + str(x))

    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v2",
        "auto",
        "b",
        "s",
        "q",
        [],
        True,
        "grok",
        "http://llm",
        None,
    )
    assert any("business_logic" in n for n in tc.trace["notes"])
    assert tc.toon_on is True
    assert any("TOON" in n for n in tc.trace["notes"])


@pytest.mark.asyncio
async def test_setup_turn_context_catalog_lint_when_debug(patched_loop, monkeypatch):
    req = _minimal_chat_req()
    req["guidance"] = {
        "debug": True,
        "injections": {
            "business_logic": [
                {"id": "a", "rule": "Always prefer find for Beer."},
                {"id": "b", "rule": "Never use find for Beer."},
            ]
        },
    }

    async def fake_catalog(*_a, **_k):
        return req, "local"

    monkeypatch.setattr(loop_mod, "load_chat_request", fake_catalog)
    monkeypatch.setattr(loop_mod, "apply_injected_business_logic", lambda r: r)
    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v2",
        "auto",
        "b",
        "s",
        "q",
        [],
        False,
        "grok",
        "http://llm",
        None,
    )
    assert "catalog_lint" in tc.trace
    assert tc.trace["catalog_lint"]["finding_count"] >= 1
    assert any("catalog_lint:" in n for n in tc.trace["notes"])


@pytest.mark.asyncio
async def test_setup_turn_context_hash_exception(patched_loop, monkeypatch):
    monkeypatch.setattr(
        loop_mod,
        "extract_stamped_hash",
        lambda _r: (_ for _ in ()).throw(ValueError("bad")),
    )
    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v1",
        "auto",
        "b",
        "s",
        "q",
        [],
        False,
        "grok",
        "http://llm",
        "c",
    )
    assert tc.stamped_h == ""
    assert tc.current_content_h == ""


@pytest.mark.asyncio
async def test_setup_turn_context_cache_hints(patched_loop, monkeypatch):
    monkeypatch.setattr(loop_mod, "cache_hints", lambda *_a: ({"X-Cache": "1"}, {"cache": True}))
    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v2",
        "auto",
        "b",
        "s",
        "q",
        [],
        False,
        "grok",
        "http://llm",
        "c",
    )
    assert tc.cache_headers == {"X-Cache": "1"}
    assert any("prompt cache" in n and "hints sent" in n for n in tc.trace["notes"])


@pytest.mark.asyncio
async def test_run_agent_direct_answer(patched_loop, monkeypatch):
    async def llm_answer(*_a, **_k):
        return "done", True, None

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_answer)
    monkeypatch.setattr(
        loop_mod,
        "execute_tool_calls",
        lambda *_a, **_k: (None, False, {}, _empty_outcome()),
    )

    class ObserveHooks(AgentHooks):
        def __init__(self):
            self.events = []

        async def observe(self, event, data):
            self.events.append(event)

    hooks = ObserveHooks()
    answer, trace, messages, meta = await loop_mod.run_agent(
        "http://zeus",
        {"auth_mode": "none"},
        "http://llm",
        "key",
        "model",
        "v2",
        "analytics",
        "beer-sample",
        "_default",
        "_default",
        "find beers",
        [],
        hooks=hooks,
    )
    assert answer == "done"
    assert trace["rounds"] == 1
    assert "run_start" in hooks.events
    assert "final_answer" in hooks.events
    assert meta["session_id"] == "sess-loop"


@pytest.mark.asyncio
async def test_run_agent_tool_round_breaks_early(patched_loop, monkeypatch):
    async def llm_tools(*_a, **_k):
        return None, False, {"role": "assistant", "tool_calls": [{"id": "c1"}]}

    async def tools_done(*_a, **_k):
        return (
            "early answer",
            True,
            {},
            _empty_outcome(return_seen=True, terminal_summary="early answer"),
        )

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_tools)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_done)

    async def no_insight(*_a, **_k):
        return ""

    monkeypatch.setattr(loop_mod, "force_final_llm_answer", no_insight)

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "question",
        [],
    )
    assert answer == "early answer"
    assert trace["rounds"] == 1
    assert trace.get("ai_process_result_exit") == "insight"


@pytest.mark.asyncio
async def test_run_agent_tool_round_then_answer(patched_loop, monkeypatch):
    call = {"n": 0}

    async def llm_twice(rnd, *_a, **_k):
        if call["n"] == 0:
            call["n"] += 1
            return None, False, {"role": "assistant", "tool_calls": [{"id": "c1"}]}
        return "final", True, None

    async def tools_once(*_a, **_k):
        return None, False, {"X-Zeus-Session": "sid"}, _empty_outcome()

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_twice)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_once)

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "question",
        [],
    )
    assert answer == "final"
    assert trace["rounds"] == 2


@pytest.mark.asyncio
async def test_run_agent_should_continue_stops(patched_loop, monkeypatch):
    async def llm_tool(*_a, **_k):
        return None, False, {"role": "assistant", "tool_calls": []}

    async def tools_continue(*_a, **_k):
        return None, False, {}, _empty_outcome()

    class StopHooks(AgentHooks):
        async def should_continue(self, round_num, messages, ctx):
            return False

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_tool)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_continue)

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
        hooks=StopHooks(),
    )
    assert "should_continue hook" in answer
    assert any("should_continue" in n for n in trace["notes"])


@pytest.mark.asyncio
async def test_run_agent_max_rounds_exhausted(patched_loop, monkeypatch):
    async def llm_always_tools(*_a, **_k):
        return None, False, {"role": "assistant", "tool_calls": [{"id": "x"}]}

    async def tools_never_done(*_a, **_k):
        return None, False, {}, _empty_outcome()

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_always_tools)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_never_done)
    monkeypatch.setattr(loop_mod, "MAX_ROUNDS", 2)

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
    )
    assert "Ran out of tool rounds" in answer
    assert trace["rounds"] == 2

    monkeypatch.setattr(loop_mod, "MAX_ROUNDS", MAX_ROUNDS)


@pytest.mark.asyncio
async def test_run_agent_prior_turns_delta(patched_loop, monkeypatch):
    prior = [{"role": "user", "content": "old"}]

    async def llm_done(*_a, **_k):
        return "ok", True, None

    captured = {}

    async def capture_commit(
        zeus_url,
        sid,
        enable_sessions,
        this_user_round,
        contract_id,
        contract_hash,
        chat_req,
        produced_delta,
        prior_turns,
        this_turn_reqs,
        trace,
        zeus_headers,
    ):
        captured["delta"] = produced_delta
        return {
            "session_id": sid,
            "round": 1,
            "enabled": False,
            "contract_id": "",
            "contract_hash": "",
            "contract_status": "none",
            "req_ids": [],
        }

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_done)
    monkeypatch.setattr(loop_mod, "commit_session_turn", capture_commit)

    await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "new question",
        prior,
    )
    assert captured["delta"][-1]["content"] == "new question"


@pytest.mark.asyncio
async def test_run_agent_structured_returns_five_tuple(patched_loop, monkeypatch):
    from tests.fixtures.catalog_brief import base_chat_req

    async def fake_catalog(*_a, **_k):
        return base_chat_req(), "local"

    async def llm_answer(*_a, **_k):
        return "summary text", True, None

    monkeypatch.setattr(loop_mod, "load_chat_request", fake_catalog)
    monkeypatch.setattr(loop_mod, "run_llm_round", llm_answer)
    monkeypatch.setattr(
        loop_mod,
        "execute_tool_calls",
        lambda *_a, **_k: (None, False, {}, _empty_outcome()),
    )

    result = await loop_mod.run_agent(
        "http://zeus",
        {"auth_mode": "none"},
        "http://llm",
        "key",
        "model",
        "v2",
        "analytics",
        "beer-sample",
        "_default",
        "_default",
        "find beers",
        [],
        structured=True,
    )
    assert len(result) == 5
    answer, trace, messages, meta, structured = result
    assert answer == "summary text"
    assert structured.answer == "summary text"
    assert structured.zeus_data == []
    assert trace["structured_response"]["zeus_data_count"] == 0


@pytest.mark.asyncio
async def test_run_agent_structured_false_returns_four_tuple(patched_loop, monkeypatch):
    async def llm_answer(*_a, **_k):
        return "plain", True, None

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_answer)
    monkeypatch.setattr(
        loop_mod,
        "execute_tool_calls",
        lambda *_a, **_k: (None, False, {}, _empty_outcome()),
    )

    result = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
        structured=False,
    )
    assert len(result) == 4


@pytest.mark.asyncio
async def test_ai_process_result_false_cheap_after_tools(patched_loop, monkeypatch):
    """ai_process_result=false: after Zeus data, thin final — no second LLM hop."""
    from zeus_client.agent.settings import ClientSettings

    llm_calls = {"n": 0}
    force_final_calls = {"n": 0}

    async def llm_tools_once(*_a, **_k):
        llm_calls["n"] += 1
        return None, False, {"role": "assistant", "tool_calls": [{"id": "c1"}]}

    async def tools_with_data(*_a, **_k):
        return (
            None,
            False,
            {},
            _empty_outcome(
                tools_executed=1,
                tools_with_data=1,
                tool_arg_summary="Businesses in Reno from the graph",
            ),
        )

    async def should_not_force_final(*_a, **_k):
        force_final_calls["n"] += 1
        return "should not run"

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_tools_once)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_with_data)
    monkeypatch.setattr(loop_mod, "force_final_llm_answer", should_not_force_final)

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
        settings=ClientSettings(ai_process_result=False, company_context="Beer Co"),
    )
    assert answer == "Businesses in Reno from the graph"
    assert force_final_calls["n"] == 0
    assert trace.get("ai_process_result_exit") == "cheap_final"
    assert any("without second LLM hop" in n for n in trace["notes"])
    assert llm_calls["n"] == 1  # plan hop only


@pytest.mark.asyncio
async def test_ai_process_result_false_cheap_static_without_tool_summary(patched_loop, monkeypatch):
    from zeus_client.agent.settings import ClientSettings
    from zeus_client.agent.tool_round import CHEAP_FINAL_STATIC_ANSWER

    async def llm_tools_once(*_a, **_k):
        return None, False, {"role": "assistant", "tool_calls": [{"id": "c1"}]}

    async def tools_with_data(*_a, **_k):
        return None, False, {}, _empty_outcome(tools_executed=1, tools_with_data=1)

    async def should_not_force_final(*_a, **_k):
        raise AssertionError("force_final_llm_answer must not run on cheap path")

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_tools_once)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_with_data)
    monkeypatch.setattr(loop_mod, "force_final_llm_answer", should_not_force_final)

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
        settings=ClientSettings(ai_process_result=False),
    )
    assert answer == CHEAP_FINAL_STATIC_ANSWER
    assert trace.get("ai_process_result_exit") == "cheap_final"


@pytest.mark.asyncio
async def test_ai_process_result_false_cheap_terminal_on_return(patched_loop, monkeypatch):
    async def llm_tools(*_a, **_k):
        return None, False, {"role": "assistant", "tool_calls": [{"id": "c1"}]}

    async def tools_return(*_a, **_k):
        return (
            "thin summary",
            True,
            {},
            _empty_outcome(
                return_seen=True,
                terminal_summary="thin summary",
            ),
        )

    insight_calls = {"n": 0}

    async def should_not_insight(*_a, **_k):
        insight_calls["n"] += 1
        return "should not run"

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_tools)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_return)
    monkeypatch.setattr(loop_mod, "force_final_llm_answer", should_not_insight)

    from zeus_client.agent.settings import ClientSettings

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
        settings=ClientSettings(ai_process_result=False),
    )
    assert answer == "thin summary"
    assert insight_calls["n"] == 0
    assert trace.get("ai_process_result_exit") == "cheap_terminal"


@pytest.mark.asyncio
async def test_ai_process_result_true_insight_after_return(patched_loop, monkeypatch):
    async def llm_tools(*_a, **_k):
        return None, False, {"role": "assistant", "tool_calls": [{"id": "c1"}]}

    async def tools_return(*_a, **_k):
        return "thin", True, {}, _empty_outcome(return_seen=True, terminal_summary="thin")

    async def insight(*_a, **_k):
        return "rich narration of Zeus rows"

    monkeypatch.setattr(loop_mod, "run_llm_round", llm_tools)
    monkeypatch.setattr(loop_mod, "execute_tool_calls", tools_return)
    monkeypatch.setattr(loop_mod, "force_final_llm_answer", insight)

    from zeus_client.agent.settings import ClientSettings

    answer, trace, _, _ = await loop_mod.run_agent(
        "http://zeus",
        {},
        "http://llm",
        "key",
        "model",
        "v2",
        "auto",
        "b",
        "s",
        "c",
        "q",
        [],
        settings=ClientSettings(ai_process_result=True),
    )
    assert answer == "rich narration of Zeus rows"
    assert trace.get("ai_process_result_exit") == "insight"


@pytest.mark.asyncio
async def test_setup_turn_context_notes_ai_process_default(patched_loop):
    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v2",
        "auto",
        "b",
        "s",
        "q",
        [],
        False,
        "grok",
        "http://llm",
        None,
    )
    assert any("ai_process_result=true" in n for n in tc.trace["notes"])
    assert tc.ctx["ai_process_result"] is True


@pytest.mark.asyncio
async def test_setup_turn_context_ai_process_false(patched_loop):
    from zeus_client.agent.settings import ClientSettings

    tc = await loop_mod.setup_turn_context(
        "http://zeus",
        {},
        "v2",
        "auto",
        "b",
        "s",
        "q",
        [],
        False,
        "grok",
        "http://llm",
        None,
        settings=ClientSettings(ai_process_result=False),
    )
    assert any("ai_process_result=false" in n for n in tc.trace["notes"])
    assert tc.ctx["ai_process_result"] is False
