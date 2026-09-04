"""Agent turn must setup/commit durable session + post multi-hop session-trace."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from zeus_client.adapters.zeus_http.session import SessionHttpResult
from zeus_client.application.agent_turn import run_agent_turn
from zeus_client.application.session_lifecycle import CommitResult
from zeus_client.config.models import ClientSettings, DebugPolicy
from zeus_client.domain.errors import ErrorCode, LlmError
from zeus_client.domain.messages import TurnRequest, TurnStatus
from zeus_client.domain.session import SessionHandle
from zeus_client.ports import LlmRequest, LlmResponse, VerbHopResult, VerbRequest


@dataclass
class ScriptedLlm:
    script: list[Any] = field(default_factory=list)
    calls: list[LlmRequest] = field(default_factory=list)

    async def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls.append(req)
        if not self.script:
            return LlmResponse(content="(empty)", tool_calls=())
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class ScriptedZeus:
    results: dict[str, VerbHopResult] = field(default_factory=dict)
    calls: list[VerbRequest] = field(default_factory=list)

    async def resolve_auth(self, target, *, force: bool = False):
        return type("A", (), {"headers": {}, "mode": "none"})()

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.calls.append(req)
        if req.verb in self.results:
            return self.results[req.verb]
        return VerbHopResult(ok=True, status_code=200, req_id=f"req-{req.verb}", body={})


@dataclass
class FakeSessionClient:
    posts: list[dict[str, Any]] = field(default_factory=list)

    async def post_trace(self, **kwargs: Any) -> SessionHttpResult:
        self.posts.append(dict(kwargs))
        return SessionHttpResult(
            ok=True,
            status_code=201,
            body={"contract_status": "match"},
            url="http://z/v2/session/trace",
            req_id="trace-post-1",
        )


@dataclass
class FakeLifecycle:
    client: FakeSessionClient
    setups: list[dict[str, Any]] = field(default_factory=list)
    commits: list[tuple[SessionHandle, dict[str, Any]]] = field(default_factory=list)
    setup_exc: Exception | None = None

    async def setup(self, **kwargs: Any) -> SessionHandle:
        self.setups.append(dict(kwargs))
        if self.setup_exc:
            raise self.setup_exc
        return SessionHandle(
            session_id="sess_join_1",
            round=1,
            chat_id=str(kwargs.get("chat_id") or ""),
            contract_id="cid-1",
            contract_hash="md5:abc",
            contract_status="match",
            created=True,
            enabled=True,
        )

    async def commit(self, handle: SessionHandle, **kwargs: Any) -> CommitResult:
        self.commits.append((handle, dict(kwargs)))
        return CommitResult(
            ok=True,
            handle=handle.with_updates(created=False, round=2),
            turn_req_id="turn-req-1",
        )


def _tc(name: str, args: dict, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _return_args() -> dict:
    return {
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
        "subject_confidence": 0.9,
        "jail_break_attempt": 0.0,
        "wish_i_knew": [],
        "node_refs": ["file::0055735878630271"],
        "entity_refs": ["airport_7240"],
    }


FIND_TOOL = {
    "type": "function",
    "function": {"name": "find", "parameters": {"type": "object", "properties": {}}},
}
RETURN_TOOL = {
    "type": "function",
    "function": {"name": "return", "parameters": {"type": "object", "properties": {}}},
}


@pytest.mark.asyncio
async def test_enable_sessions_posts_trace_join_then_commits_turn() -> None:
    """Detective join: setup sid → POST /v2/session/trace on hop req_id → commit turn."""
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc(
                        "find",
                        {"entity_type": "Airport", "where": {"country": "United States"}},
                        "c1",
                    ),
                    _tc("return", _return_args(), "c2"),
                ),
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-airports",
                body={"result": {"items": [{"name": "Sleetmute Airport"}], "returned_count": 1}},
            )
        }
    )
    client = FakeSessionClient()
    life = FakeLifecycle(client=client)

    result = await run_agent_turn(
        TurnRequest(
            message="give the list of airports in US",
            tools=(FIND_TOOL, RETURN_TOOL),
            chat_id="chat_airports",
            chat_request={"messages": [{"role": "system", "content": "sys"}]},
            settings=ClientSettings(ai_process_result=False, durable_sessions=True),
            enable_sessions=True,
        ),
        llm=llm,
        zeus=zeus,
        session_lifecycle=life,
    )

    assert result.status is TurnStatus.OK
    assert life.setups, "expected SessionLifecycle.setup"
    assert life.setups[0]["user_message"] == "give the list of airports in US"
    assert life.setups[0]["chat_id"] == "chat_airports"

    assert client.posts, "expected POST /v2/session/trace"
    post = client.posts[0]
    assert post["session_id"] == "sess_join_1"
    assert post["turn_id"] == result.debug.turn_id
    assert post["req_id"] == "req-find-airports"
    assert post["client_round"] == 1
    zresp = post["zeus_response"]
    assert zresp["aggregate"] is True
    assert zresp["primary_req_id"] == "req-find-airports"
    assert zresp["req_ids"] == ["req-find-airports"]
    la = zresp["layer_a"]
    assert la["query_decomposition"]["entity"] == "Airport"
    assert la["query_decomposition"]["intent"] == "List"
    assert la["decomposition"]["predicates"]["country"] == "United States"
    assert la["confidence"] == "high"
    assert la["policy_action"] == "answer"
    assert la.get("via") == "client_terminate"

    assert life.commits, "expected SessionLifecycle.commit"
    assert result.session is not None
    assert result.session.session_id == "sess_join_1"
    assert result.debug.preferred_req_id == "req-find-airports"
    sess = (result.debug.public_trace or {}).get("session") or {}
    assert sess.get("req_ids") == ["req-find-airports"]
    assert sess.get("preferred_req_id") == "req-find-airports"


@pytest.mark.asyncio
async def test_session_setup_failure_does_not_fail_turn() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="hello", tool_calls=())])
    life = FakeLifecycle(client=FakeSessionClient(), setup_exc=RuntimeError("cb down"))
    result = await run_agent_turn(
        TurnRequest(message="hi", enable_sessions=True),
        llm=llm,
        zeus=None,
        session_lifecycle=life,
    )
    assert result.status is TurnStatus.OK
    assert result.answer == "hello"
    assert any("session_setup_failed" in n for n in result.debug.notes)
    assert not life.commits
    assert not life.client.posts


@pytest.mark.asyncio
async def test_agent_api_enable_sessions_uses_injected_lifecycle() -> None:
    from zeus_client.api.agent import AgentAPI
    from zeus_client.config.models import (
        DebugPolicy,
        LlmProviderConfig,
        RuntimeConfig,
        ZeusEndpointConfig,
    )
    from zeus_client.runtime import Services, ZeusRuntime

    llm = ScriptedLlm(script=[LlmResponse(content="ok", tool_calls=())])
    client = FakeSessionClient()
    life = FakeLifecycle(client=client)
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url="http://127.0.0.1:8080"),
        llm=LlmProviderConfig(provider="test", base_url="http://llm", model="m"),
        settings=ClientSettings(ai_process_result=False, durable_sessions=True),
        debug=DebugPolicy(detective_briefing=False),
    )
    svc = Services()
    svc.llm = llm
    svc.session_lifecycle = life  # type: ignore[attr-defined]
    api = AgentAPI(ZeusRuntime(cfg, services=svc))
    result = await api.run_turn("hi", enable_sessions=True)
    assert result.status is TurnStatus.OK
    assert life.setups
    assert result.session is not None
    assert result.session.session_id == "sess_join_1"


_SYSTEM_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "system_with_brief_mini.txt"
).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_session_trace_posts_hub_inject_bag_on_rewind() -> None:
    """ZCP-114: every tool-hop join has Hub-shaped inject; Direct body has no mini."""
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc(
                        "find",
                        {"entity_type": "hotel", "where": {"city": "Paris"}},
                        "c1",
                    ),
                    _tc("return", _return_args(), "c2"),
                ),
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-hotel",
                body={"result": {"items": [{"name": "Hotel"}], "returned_count": 1}},
            )
        }
    )
    client = FakeSessionClient()
    life = FakeLifecycle(client=client)

    result = await run_agent_turn(
        TurnRequest(
            message="hotels in Paris",
            tools=(FIND_TOOL, RETURN_TOOL),
            chat_id="chat_hotels",
            chat_request={"messages": [{"role": "system", "content": _SYSTEM_FIXTURE}]},
            settings=ClientSettings(ai_process_result=False, durable_sessions=True),
            enable_sessions=True,
        ),
        llm=llm,
        zeus=zeus,
        session_lifecycle=life,
        debug_policy=DebugPolicy(rewind=True),
    )

    assert result.status is TurnStatus.OK
    assert client.posts, "expected POST /v2/session/trace"
    for post in client.posts:
        inj = post["zeus_response"]["inject"]
        assert inj["source"] == "client_llm"
        assert inj["mini_schema"]["present"] is True
        assert len(inj["mini_schema"]["sha12"]) == 12
        int(inj["mini_schema"]["sha12"], 16)
        assert "hotel" in inj["mini_schema"]["entity_types"]
        assert inj["mini_schema"]["text"].startswith("## MINI-SCHEMA")
        assert "text" in inj["scope_brief"]
        assert post["rewind"] is True
        assert post["turn_id"] == result.debug.turn_id

    hop_headers = dict(zeus.calls[0].headers)
    posted_inj = client.posts[0]["zeus_response"]["inject"]
    assert hop_headers["X-Zeus-Chat-Session-Id"] == "sess_join_1"
    assert hop_headers["X-Zeus-Mini-Sha12"] == posted_inj["mini_schema"]["sha12"]
    assert hop_headers["X-Zeus-Brief-Sha12"] == posted_inj["scope_brief"]["sha12"]
    assert "X-Zeus-Session" not in hop_headers
    assert "X-Zeus-Req-Id" not in hop_headers

    public_inj = (result.debug.public_trace or {}).get("inject") or {}
    assert public_inj["mini_schema"]["present"] is True
    assert (
        public_inj["mini_schema"]["sha12"]
        == client.posts[0]["zeus_response"]["inject"]["mini_schema"]["sha12"]
    )

    assert zeus.calls, "expected Direct find hop"
    for call in zeus.calls:
        dumped = json.dumps(call.body)
        assert "## MINI-SCHEMA" not in dumped
        assert "## SCOPE BRIEF" not in dumped
        assert "rewind" not in call.body


_USAGE_R1 = {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}


@pytest.mark.asyncio
async def test_session_trace_tokens_match_debug_bundle() -> None:
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc("find", {"entity_type": "Airport"}, "c1"),
                    _tc("return", _return_args(), "c2"),
                ),
                usage=_USAGE_R1,
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-airports",
                body={"result": {"items": [{"name": "Sleetmute Airport"}], "returned_count": 1}},
            )
        }
    )
    client = FakeSessionClient()
    life = FakeLifecycle(client=client)
    result = await run_agent_turn(
        TurnRequest(
            message="airports",
            tools=(FIND_TOOL, RETURN_TOOL),
            chat_id="chat_tok",
            settings=ClientSettings(ai_process_result=False, durable_sessions=True),
            enable_sessions=True,
        ),
        llm=llm,
        zeus=zeus,
        session_lifecycle=life,
    )
    assert result.status is TurnStatus.OK
    assert client.posts
    tok = client.posts[0]["zeus_response"]["tokens"]
    assert tok["prompt"] == result.debug.tokens["prompt"] == 10
    assert tok["completion"] == result.debug.tokens["completion"] == 1
    assert tok["total"] == result.debug.tokens["total"] == 11
    assert tok["rounds"] == 1
    assert tok["ok"] is True
    assert "cached" not in tok
    assert "extra" not in tok


@pytest.mark.asyncio
async def test_session_trace_omits_tokens_when_llm_usage_unknown() -> None:
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc("find", {"entity_type": "Airport"}, "c1"),
                    _tc("return", _return_args(), "c2"),
                ),
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-airports",
                body={"result": {"items": [{"name": "X"}], "returned_count": 1}},
            )
        }
    )
    client = FakeSessionClient()
    life = FakeLifecycle(client=client)
    await run_agent_turn(
        TurnRequest(
            message="airports",
            tools=(FIND_TOOL, RETURN_TOOL),
            settings=ClientSettings(ai_process_result=False, durable_sessions=True),
            enable_sessions=True,
        ),
        llm=llm,
        zeus=zeus,
        session_lifecycle=life,
    )
    assert client.posts
    assert "tokens" not in client.posts[0]["zeus_response"]


@pytest.mark.asyncio
async def test_session_trace_ok_false_when_later_llm_round_fails() -> None:
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(_tc("find", {"entity_type": "Airport"}, "c1"),),
                usage=_USAGE_R1,
            ),
            LlmError(
                code=ErrorCode.AGENT_LLM_REQUEST_FAILED,
                component="llm",
                public_message="boom",
            ),
        ]
    )
    zeus = ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-find-airports",
                body={"result": {"items": [{"name": "X"}], "returned_count": 1}},
            )
        }
    )
    client = FakeSessionClient()
    life = FakeLifecycle(client=client)
    result = await run_agent_turn(
        TurnRequest(
            message="airports",
            tools=(FIND_TOOL, RETURN_TOOL),
            settings=ClientSettings(ai_process_result=True, durable_sessions=True, max_rounds=3),
            enable_sessions=True,
        ),
        llm=llm,
        zeus=zeus,
        session_lifecycle=life,
    )
    assert result.status is TurnStatus.ERROR
    assert client.posts, "expected join even after later LLM failure"
    tok = client.posts[0]["zeus_response"]["tokens"]
    assert tok["prompt"] == 10
    assert tok["rounds"] == 1
    assert tok["ok"] is False
    assert client.posts[0]["req_id"] == "req-find-airports"
