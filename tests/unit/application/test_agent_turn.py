"""Agent turn use-case — fake LlmPort + ZeusPort dialogues (ZCP-18)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

import pytest

from zeus_client_v2.application.agent_turn import (
    CHEAP_FINAL_STATIC_ANSWER,
    AgentTurnUseCase,
    run_agent_turn,
)
from zeus_client_v2.application.middleware import MiddlewareChain, MiddlewareContext, NoopMiddleware
from zeus_client_v2.config.models import ClientSettings, DataTarget
from zeus_client_v2.domain.journal import InMemoryJournal
from zeus_client_v2.domain.messages import TurnRequest, TurnStatus
from zeus_client_v2.ports import LlmRequest, LlmResponse, VerbHopResult, VerbRequest


@dataclass
class ScriptedLlm:
    """Queue of LlmResponse / Exception per complete() call."""

    script: list[Any] = field(default_factory=list)
    calls: list[LlmRequest] = field(default_factory=list)

    async def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls.append(req)
        if not self.script:
            return LlmResponse(content="(empty script)", tool_calls=())
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class ScriptedZeus:
    """Map verb → VerbHopResult; records calls."""

    results: dict[str, VerbHopResult] = field(default_factory=dict)
    calls: list[VerbRequest] = field(default_factory=list)

    async def resolve_auth(self, target: DataTarget, *, force: bool = False):
        return type("A", (), {"headers": {}, "mode": "none"})()

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.calls.append(req)
        if req.verb in self.results:
            return self.results[req.verb]
        return VerbHopResult(
            ok=True,
            status_code=200,
            req_id=f"req-{req.verb}",
            body={"result": {"items": [{"id": "1"}]}},
        )


def _tc(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _return_args(**extra) -> dict:
    base = {
        "summary": "Found two beers in Tampa.",
        "query_decomposition": {"intent": "List", "entity": "Beer"},
        "decomposition": {"targets": [{"entity_type": "Beer"}]},
        "confidence": "high",
        "policy_action": "answer",
    }
    base.update(extra)
    return base


FIND_TOOL = {
    "type": "function",
    "function": {
        "name": "find",
        "parameters": {"type": "object", "properties": {}},
    },
}
RETURN_TOOL = {
    "type": "function",
    "function": {
        "name": "return",
        "parameters": {"type": "object", "properties": {}},
    },
}


@pytest.mark.asyncio
async def test_direct_answer_no_tools():
    llm = ScriptedLlm(
        script=[LlmResponse(content="Hello from Zeus.", tool_calls=())]
    )
    result = await run_agent_turn(
        TurnRequest(message="hi", tools=()),
        llm=llm,
        zeus=None,
    )
    assert result.status is TurnStatus.OK
    assert result.answer == "Hello from Zeus."
    assert result.debug.rounds == 1
    assert result.debug.ai_process_result_exit == "direct"
    assert "wish_i_knew" not in result.answer


@pytest.mark.asyncio
async def test_single_tool_then_return_insight():
    """Insight path: find → return → second LLM hop (no tools)."""
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc("find", {"entity_type": "Beer", "limit": 2}, "c1"),
                    _tc("return", _return_args(), "c2"),
                ),
            ),
            LlmResponse(
                content="There are two great beers to try.",
                tool_calls=(),
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-1",
                body={"result": {"items": [{"name": "IPA"}, {"name": "Stout"}]}},
            )
        }
    )
    result = await run_agent_turn(
        TurnRequest(
            message="list beers",
            tools=(FIND_TOOL, RETURN_TOOL),
            settings=ClientSettings(ai_process_result=True, max_rounds=4),
        ),
        llm=llm,
        zeus=zeus,
        journal=InMemoryJournal(),
    )
    assert result.status is TurnStatus.OK
    assert result.answer == "There are two great beers to try."
    assert result.debug.ai_process_result_exit == "insight"
    assert len(zeus.calls) == 1
    assert zeus.calls[0].verb == "find"
    assert zeus.calls[0].allow_pipeline is True
    # second LLM call has no tools
    assert llm.calls[1].tools == ()
    assert result.structured is not None
    assert result.structured.policy == "answer"
    assert "wish_i_knew" not in result.answer
    assert result.debug.hops and result.debug.hops[0]["req_id"] == "req-find-1"


@pytest.mark.asyncio
async def test_cheap_terminal_no_insight_hop():
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc("find", {"entity_type": "Beer"}, "c1"),
                    _tc("return", _return_args(summary="Terminal cheap summary."), "c2"),
                ),
            ),
        ]
    )
    zeus = ScriptedZeus()
    result = await run_agent_turn(
        TurnRequest(
            message="list beers",
            tools=(FIND_TOOL, RETURN_TOOL),
            settings=ClientSettings(ai_process_result=False, max_rounds=4),
        ),
        llm=llm,
        zeus=zeus,
    )
    assert result.answer == "Terminal cheap summary."
    assert result.debug.ai_process_result_exit == "cheap_terminal"
    assert len(llm.calls) == 1  # no insight hop


@pytest.mark.asyncio
async def test_cheap_final_after_data_without_return():
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc(
                        "find",
                        {"entity_type": "Beer", "summary": "From tool args."},
                        "c1",
                    ),
                ),
            ),
        ]
    )
    zeus = ScriptedZeus()
    result = await run_agent_turn(
        TurnRequest(
            message="find beers",
            tools=(FIND_TOOL,),
            settings=ClientSettings(ai_process_result=False, max_rounds=3),
        ),
        llm=llm,
        zeus=zeus,
    )
    assert result.answer == "From tool args."
    assert result.debug.ai_process_result_exit == "cheap_final"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_cheap_final_static_when_no_tool_summary():
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(_tc("find", {"entity_type": "Beer"}, "c1"),),
            ),
        ]
    )
    result = await run_agent_turn(
        TurnRequest(
            message="find",
            tools=(FIND_TOOL,),
            settings=ClientSettings(ai_process_result=False),
        ),
        llm=llm,
        zeus=ScriptedZeus(),
    )
    assert result.answer == CHEAP_FINAL_STATIC_ANSWER


@pytest.mark.asyncio
async def test_peel_layer_a_dump_from_insight():
    """Insight content that is a Layer A dump must peel to summary."""
    dump = (
        "```\n"
        'summary: "Peeled salon answer."\n'
        "confidence: med\n"
        'query_decomposition: {"intent": "x"}\n'
        'decomposition: {"targets": []}\n'
        "policy_action: answer\n"
        "wish_i_knew: [{\"gap\": \"secret\"}]\n"
        "```"
    )
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(_tc("return", _return_args(summary="Bag summary."), "c1"),),
            ),
            LlmResponse(content=dump, tool_calls=()),
        ]
    )
    result = await run_agent_turn(
        TurnRequest(
            message="q",
            tools=(RETURN_TOOL,),
            settings=ClientSettings(ai_process_result=True, max_rounds=3),
        ),
        llm=llm,
        zeus=ScriptedZeus(),
    )
    assert result.answer == "Peeled salon answer."
    assert "wish_i_knew" not in result.answer
    assert "secret" not in result.answer


@pytest.mark.asyncio
async def test_empty_message_errors():
    result = await run_agent_turn(
        TurnRequest(message="  "),
        llm=ScriptedLlm(),
    )
    assert result.status is TurnStatus.ERROR
    assert result.error is not None
    assert result.error.code == "050002"


@pytest.mark.asyncio
async def test_middleware_before_zeus_mutates_args():
    class MutateMw(NoopMiddleware):
        name = "mutate"

        async def before_zeus(self, ctx: MiddlewareContext, name: str, args: dict):
            args = dict(args)
            args["limit"] = 99
            return args

    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(_tc("find", {"entity_type": "Beer", "limit": 1}, "c1"),),
                # no return — cheap path after data
            ),
        ]
    )
    zeus = ScriptedZeus()
    chain = MiddlewareChain()
    chain.add(MutateMw())
    await run_agent_turn(
        TurnRequest(
            message="q",
            tools=(FIND_TOOL,),
            settings=ClientSettings(ai_process_result=False),
        ),
        llm=llm,
        zeus=zeus,
        middleware=chain,
    )
    assert zeus.calls[0].body["limit"] == 99


@pytest.mark.asyncio
async def test_ai_process_raises_max_rounds_floor():
    llm = ScriptedLlm(
        script=[LlmResponse(content="ok", tool_calls=())]
    )
    result = await run_agent_turn(
        TurnRequest(
            message="hi",
            settings=ClientSettings(ai_process_result=True, max_rounds=1),
        ),
        llm=llm,
    )
    assert any("max_rounds raised to 2" in n for n in result.debug.notes)


@pytest.mark.asyncio
async def test_use_case_and_pipeline_allow_flag():
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc(
                        "pipeline",
                        {"steps": [], "turn_complete": True, "summary": "Pipe done."},
                        "c1",
                    ),
                ),
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "pipeline": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-pipe",
                body={"turn_complete": True, "summary": "Pipe done."},
            )
        }
    )
    uc = AgentTurnUseCase(llm=llm, zeus=zeus)
    result = await uc.run(
        TurnRequest(
            message="run",
            tools=(
                {
                    "type": "function",
                    "function": {"name": "pipeline", "parameters": {}},
                },
            ),
            settings=ClientSettings(ai_process_result=False),
        )
    )
    assert zeus.calls[0].allow_pipeline is True
    assert result.debug.ai_process_result_exit == "cheap_terminal"
    assert "Pipe done" in result.answer
