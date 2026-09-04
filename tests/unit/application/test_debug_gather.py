"""E2E debug gather on agent TurnResult (ZCP-85)."""

from __future__ import annotations

import json

import pytest

from zeus_client import __version__
from zeus_client.application.agent_turn import _tools_from_request, run_agent_turn
from zeus_client.application.debug_export import export_journal_redacted
from zeus_client.application.detective.extract import catalog_flags_of, sha12, slice_block
from zeus_client.config.models import ClientSettings
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.domain.messages import TurnRequest
from zeus_client.ports import LlmResponse, VerbHopResult


def _tc(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.mark.asyncio
async def test_finish_stamps_chat_and_empty_req_ids_on_direct_exit() -> None:
    from tests.unit.application.test_agent_turn import ScriptedLlm

    journal = InMemoryJournal()
    result = await run_agent_turn(
        TurnRequest(message="hi", chat_id="chat_x"),
        llm=ScriptedLlm(script=[LlmResponse(content="hello", tool_calls=())]),
        zeus=None,
        journal=journal,
        zeus_url="http://127.0.0.1:8080",
    )
    from zeus_client.domain.ids import is_uuid_v4

    assert is_uuid_v4(result.debug.turn_id)
    assert result.debug.chat_id == "chat_x"
    assert result.debug.session_id is None
    assert result.debug.req_ids == ()
    assert result.debug.preferred_req_id is None
    assert result.debug.zeus_url == "http://127.0.0.1:8080"
    assert result.debug.client_version == __version__
    assert result.debug.export_ref == result.debug.turn_id
    assert result.debug.tokens is not None
    exp = export_journal_redacted(journal, turn_id=result.debug.export_ref)
    assert any(e.get("type") == "turn.started" for e in exp.events)


@pytest.mark.asyncio
async def test_finish_stamps_req_ids_from_find_hop() -> None:
    from tests.unit.application.test_agent_turn import ScriptedLlm, ScriptedZeus

    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc("find", {"entity_type": "Airport"}),
                    _tc(
                        "return",
                        {
                            "summary": "20 US airports were returned.",
                            "query_decomposition": {
                                "intent": "List",
                                "entity": "Airport",
                                "facets": {"country": "United States"},
                            },
                            "decomposition": {
                                "targets": [{"entity_type": "Airport"}],
                                "predicates": {"country": "United States"},
                                "output": "rows",
                            },
                            "confidence": "high",
                            "policy_action": "answer",
                        },
                    ),
                ),
            )
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-airports",
                body={
                    "result": {"items": [{"name": "Sleetmute Airport"}], "returned_count": 1},
                    "meta": {"step_costs": [{"verb": "find", "result_size": 1}]},
                },
                url="http://z/v2/b/s/c/find",
            )
        }
    )
    result = await run_agent_turn(
        TurnRequest(
            message="airports",
            chat_id="chat_airports",
            tools=({"type": "function", "function": {"name": "find"}},),
            settings=ClientSettings(ai_process_result=False),
        ),
        llm=llm,
        zeus=zeus,
    )
    assert result.debug.req_ids == ("req-find-airports",)
    assert result.debug.preferred_req_id == "req-find-airports"
    hop = result.debug.hops[0]
    assert hop["url"].endswith("/find")
    assert hop.get("result_size") == 1
    la = result.debug.public_trace["layer_a"]
    assert la["query_decomposition"]["entity"] == "Airport"
    assert la["via"] == "return"
    assert "wish_i_knew" not in la
    assert "wish_i_knew" not in result.answer
    sess = result.debug.public_trace["session"]
    assert sess["req_ids"] == ["req-find-airports"]
    md = result.debug.detective["diagnosis"]["support_pack"]["markdown"]
    assert "## 1. Ids" in md
    assert "## 9. Journal export" in md


def test_tools_from_request_falls_back_to_chat_request_verbs() -> None:
    req = TurnRequest(
        message="x",
        chat_request={"verbs": [{"type": "function", "function": {"name": "find"}}]},
    )
    tools = _tools_from_request(req)
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "find"


def test_slice_sha12_is_not_whole_system() -> None:
    system = "You are helpful.\n\n## SCOPE BRIEF\nAAA\n\n## MINI-SCHEMA\nBBB\n"
    flags = catalog_flags_of(system=system)
    assert flags["brief_sha12"] == sha12(slice_block(system, "brief"))
    assert flags["brief_sha12"] != sha12(system)
    assert flags["mini_sha12"] != sha12(system)


def test_inject_for_session_trace_omits_previews_and_matches_slice() -> None:
    from zeus_client.application.detective.extract import inject_for_session_trace

    system = "You are helpful.\n\n## SCOPE BRIEF\nAAA\n\n## MINI-SCHEMA\nBBB\n"
    inj = inject_for_session_trace(system=system, source="borrowed")
    assert inj["source"] == "borrowed"
    assert inj["scope_brief"]["sha12"] == sha12(slice_block(system, "brief"))
    assert inj["mini_schema"]["sha12"] == sha12(slice_block(system, "mini"))
    assert "text" not in inj["scope_brief"]
    assert "text" not in inj["mini_schema"]
    assert "brief_preview" not in inj
    assert "mini_preview" not in inj
    assert "system_message" not in inj
    assert "has_scope_brief" not in inj
