"""ZDM-16: a beer-sample turn must not basic-auth the default yelp-data bucket."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.session import HttpxSessionClient
from zeus_client.application.agent_turn import run_agent_turn
from zeus_client.application.session_lifecycle import CommitResult
from zeus_client.config.models import ClientSettings, DataTarget, ZeusEndpointConfig
from zeus_client.domain.messages import TurnRequest
from zeus_client.domain.session import SessionHandle
from zeus_client.ports import LlmRequest, LlmResponse, VerbHopResult, VerbRequest

_PASSWORD = "zdm16-password-sentinel"
ZEUS = "http://zeus.test:8080"


@dataclass
class ScriptedLlm:
    script: list[Any] = field(default_factory=list)

    async def complete(self, req: LlmRequest) -> LlmResponse:
        if not self.script:
            return LlmResponse(content="(empty)", tool_calls=())
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class ScriptedZeus:
    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        return VerbHopResult(
            ok=True,
            status_code=200,
            req_id="req-beer-find",
            body={"result": {"items": [{"name": "Cains IPA"}], "returned_count": 1}},
        )


@dataclass
class FakeLifecycle:
    client: HttpxSessionClient

    async def setup(self, **kwargs: Any) -> SessionHandle:
        return SessionHandle(
            session_id="sess_beer_1",
            round=1,
            chat_id=str(kwargs.get("chat_id") or ""),
            contract_id="cid-beer",
            contract_hash="md5:beer",
            contract_status="match",
            created=True,
            enabled=True,
        )

    async def commit(self, handle: SessionHandle, **kwargs: Any) -> CommitResult:
        return CommitResult(ok=True, handle=handle.with_updates(created=False, round=2))


def _tc(name: str, args: dict, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@pytest.mark.asyncio
@respx.mock
async def test_beer_turn_trace_auths_prereq_bucket_only() -> None:
    seen: list[str] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/auth/session"):
            return httpx.Response(
                200,
                json={"session_id": "sid-beer-1", "expires_in": 1800, "hard_ttl_s": 43200},
            )
        return httpx.Response(201, json={"contract_status": "match"})

    respx.post(url__regex=r"http://zeus\.test:8080/.*").mock(side_effect=_capture)
    http = HttpxSessionClient(
        endpoint=ZeusEndpointConfig(
            url=ZEUS,
            auth_mode="basic",
            username="tap-user",
            password_env="ZEUS_PASSWORD",
        ),
        secrets=EnvSecretStore({"ZEUS_PASSWORD": _PASSWORD}),
    )
    llm = ScriptedLlm(
        script=[
            LlmResponse(
                content=None,
                tool_calls=(
                    _tc("find", {"entity_type": "Beer", "limit": 5}, "c1"),
                    _tc(
                        "return",
                        {
                            "summary": "Cains IPA is on tap.",
                            "query_decomposition": {"intent": "Find", "entity": "Beer"},
                            "decomposition": {"targets": [{"entity_type": "Beer"}]},
                            "confidence": "high",
                            "policy_action": "answer",
                        },
                        "c2",
                    ),
                ),
            )
        ]
    )
    result = await run_agent_turn(
        TurnRequest(
            message="ipa",
            target=DataTarget(bucket="beer-sample", scope="_default", collection="_default"),
            tools=(
                {
                    "type": "function",
                    "function": {"name": "find", "parameters": {"type": "object"}},
                },
                {
                    "type": "function",
                    "function": {"name": "return", "parameters": {"type": "object"}},
                },
            ),
            chat_request={"messages": [{"role": "system", "content": "sys"}]},
            settings=ClientSettings(ai_process_result=False, durable_sessions=True),
            enable_sessions=True,
        ),
        llm=llm,
        zeus=ScriptedZeus(),
        session_lifecycle=FakeLifecycle(client=http),
    )
    await http.aclose()
    joined = "\n".join(seen)
    assert "/v1/beer-sample/_default/auth/session" in joined
    assert "/v1/yelp-data/" not in joined
    assert "/v2/session/trace" in joined
    assert _PASSWORD not in joined
    assert "session_trace_failed" not in " ".join(result.debug.notes)
