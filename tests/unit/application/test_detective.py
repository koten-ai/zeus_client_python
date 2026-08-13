"""Detective briefing projector tests (ZCP-19)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from zeus_client_v2.application.agent_turn import run_agent_turn
from zeus_client_v2.application.detective import (
    PLAYBOOK_IDS,
    build_detective_briefing,
    detective_enabled,
    safe_build_detective_briefing,
)
from zeus_client_v2.application.detective.hub_hydrate import merge_hub_hydrate
from zeus_client_v2.config.models import ClientSettings, DebugPolicy
from zeus_client_v2.domain.messages import TurnRequest
from zeus_client_v2.ports import LlmResponse, VerbHopResult

SYSTEM_WITH_INJECT = (
    "You are helpful.\n\n"
    "## SCOPE BRIEF\n"
    "Yelp businesses in Tampa.\n\n"
    "## MINI-SCHEMA\n"
    "Business: name, city\n"
)


def test_schema_v1_keys_and_playbook_ids():
    brief = build_detective_briefing(
        turn_id="t1",
        answer="Found two salons.",
        status="ok",
        rounds=1,
        hops=(
            {
                "req_id": "req-a",
                "name": "find",
                "status": 200,
                "ok": True,
                "snippet": '{"result":{"items":[{"id":"1"}]}}',
            },
        ),
        messages=({"role": "system", "content": SYSTEM_WITH_INJECT},),
        tools=({"type": "function", "function": {"name": "find"}},),
        hub_base_url="http://127.0.0.1:9091",
        session_id="sess-1",
        target={
            "bucket": "yelp-data",
            "scope": "_default",
            "collection": "_default",
            "mode": "analytics",
        },
    )
    assert brief["version"] == 1
    assert brief["source"] == "client"
    assert brief["hub_hydrated"] is False
    assert set(brief) >= {
        "version",
        "source",
        "hub_hydrated",
        "overview",
        "prompt",
        "diagnosis",
    }
    assert brief["prompt"]["verdict"] == "pass"
    assert brief["prompt"]["inject"]["has_scope_brief"] is True
    assert brief["prompt"]["inject"]["has_mini_schema"] is True
    assert brief["overview"]["preferred_req_id"] == "req-a"
    assert "req" in brief["overview"]["hub_links"]
    assert "session" in brief["overview"]["hub_links"]
    assert brief["diagnosis"]["prompt_grade"] == "pass"
    assert "support_pack" in brief["diagnosis"]
    assert "markdown" in brief["diagnosis"]["support_pack"]
    assert set(PLAYBOOK_IDS) >= {
        "boundary_collections",
        "missing_inject",
        "tool_errors",
        "hollow_answer",
        "contract_drift",
    }


def test_overview_includes_provider_tokens_from_public_trace_steps():
    brief = build_detective_briefing(
        turn_id="t-tok",
        answer="ok",
        status="ok",
        rounds=2,
        public_trace={
            "steps": [
                {
                    "type": "llm",
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                    },
                },
                {
                    "type": "force_final",
                    "usage": {
                        "prompt_tokens": 40,
                        "completion_tokens": 12,
                        "total_tokens": 52,
                    },
                },
            ],
            "tokens": {
                "prompt": 140,
                "completion": 32,
                "total": 172,
                "cached": 0,
                "extra": 0,
                "ok": True,
            },
        },
        messages=({"role": "system", "content": SYSTEM_WITH_INJECT},),
    )
    tok = brief["overview"]["tokens"]
    assert tok is not None
    assert tok["prompt"] == 140
    assert tok["completion"] == 32
    assert tok["total"] == 172
    assert tok["ok"] is True


def test_missing_inject_playbook():
    brief = build_detective_briefing(
        answer="hi",
        messages=({"role": "system", "content": "No markers here."},),
        tools=(),
    )
    assert brief["prompt"]["verdict"] == "fail"
    ids = {p["id"] for p in brief["diagnosis"]["playbooks"]}
    assert "missing_inject" in ids


def test_boundary_collections_playbook():
    brief = build_detective_briefing(
        answer="",
        hops=(
            {
                "req_id": "r1",
                "name": "find",
                "status": 400,
                "ok": False,
                "snippet": 'unknown boundary: "collections"',
            },
        ),
        messages=({"role": "system", "content": SYSTEM_WITH_INJECT},),
        tools=({"type": "function", "function": {"name": "find"}},),
    )
    ids = {p["id"] for p in brief["diagnosis"]["playbooks"]}
    assert "boundary_collections" in ids


def test_g2_not_in_overview_answer_preview():
    brief = build_detective_briefing(
        answer="Clean answer only.",
        layer_a={
            "summary": "Clean answer only.",
            "wish_i_knew": [{"gap": "secret"}],
            "jail_break_attempt": 0.9,
        },
        messages=({"role": "system", "content": SYSTEM_WITH_INJECT},),
    )
    assert "secret" not in brief["overview"]["answer_preview"]
    assert "wish_i_knew" not in brief["overview"]["answer_preview"]


def test_kill_switch_env_and_policy():
    assert detective_enabled(env={"ZEUS_CLIENT_DETECTIVE": "0"}) is False
    assert detective_enabled(debug_policy_enabled=False, env={}) is False
    assert detective_enabled(env={"ZEUS_CLIENT_DETECTIVE": "1"}) is True
    assert (
        safe_build_detective_briefing(
            enabled=False,
            answer="x",
            messages=({"role": "system", "content": "s"},),
        )
        is None
    )
    assert (
        safe_build_detective_briefing(
            enabled=True,
            env={"ZEUS_CLIENT_DETECTIVE": "0"},
            answer="x",
        )
        is None
    )


def test_hub_hydrate_does_not_clobber_client_pass():
    base = build_detective_briefing(
        messages=({"role": "system", "content": SYSTEM_WITH_INJECT},),
        tools=({"type": "function", "function": {"name": "find"}},),
        answer="ok",
    )
    assert base["prompt"]["verdict"] == "pass"
    merged = merge_hub_hydrate(
        base,
        {"prompt_checklist": {"verdict": "fail"}, "snapshot": {}},
        preferred_req_id="req-x",
    )
    assert merged["hub_hydrated"] is True
    assert merged["source"] == "client+hub"
    assert merged["prompt"]["verdict"] == "pass"
    assert any("hub_prompt_conflict" in n for n in merged["prompt"]["notes"])


def test_safe_build_never_raises():
    out = safe_build_detective_briefing(hops=object())  # type: ignore[arg-type]
    assert out is None or isinstance(out, dict)


@dataclass
class _Llm:
    script: list = field(default_factory=list)

    async def complete(self, req):
        return self.script.pop(0)


@dataclass
class _Zeus:
    async def resolve_auth(self, *a, **k):
        return type("A", (), {"headers": {}, "mode": "none"})()

    async def call_verb(self, req):
        return VerbHopResult(
            ok=True,
            status_code=200,
            req_id="req-find",
            body={"result": {"items": [{"id": "1"}]}},
        )


@pytest.mark.asyncio
async def test_agent_turn_attaches_detective_soft():
    llm = _Llm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "return",
                            "arguments": json.dumps(
                                {
                                    "summary": "Done.",
                                    "query_decomposition": {"intent": "x"},
                                    "decomposition": {"targets": []},
                                    "confidence": "high",
                                    "policy_action": "answer",
                                }
                            ),
                        },
                    },
                ),
            ),
            LlmResponse(content="Done.", tool_calls=()),
        ]
    )
    result = await run_agent_turn(
        TurnRequest(
            message="hi",
            system_prompt=SYSTEM_WITH_INJECT,
            tools=({"type": "function", "function": {"name": "return"}},),
            settings=ClientSettings(ai_process_result=True, max_rounds=3),
        ),
        llm=llm,
        zeus=_Zeus(),
        debug_policy=DebugPolicy(detective_briefing=True),
        hub_base_url="http://hub:9091",
        env={"ZEUS_CLIENT_DETECTIVE": "1"},
    )
    assert result.debug.detective is not None
    assert result.debug.detective["version"] == 1
    assert "wish_i_knew" not in result.answer
    assert result.debug.public_trace.get("detective", {}).get("version") == 1


@pytest.mark.asyncio
async def test_agent_turn_kill_switch_skips_detective():
    llm = _Llm(script=[LlmResponse(content="plain", tool_calls=())])
    result = await run_agent_turn(
        TurnRequest(message="hi", system_prompt=SYSTEM_WITH_INJECT),
        llm=llm,
        debug_policy=DebugPolicy(detective_briefing=True),
        env={"ZEUS_CLIENT_DETECTIVE": "0"},
    )
    assert result.debug.detective is None
    assert result.answer == "plain"
