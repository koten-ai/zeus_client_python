"""Agent-turn semantic cache hooks (ZF-WISH-001)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx
from tests.unit.application.test_agent_turn import ScriptedLlm

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort
from zeus_client.application.agent_turn import run_agent_turn
from zeus_client.application.typeahead import SuggestOptions, run_typeahead_search
from zeus_client.config.models import (
    DataTarget,
    RuntimeConfig,
    SemanticCacheConfig,
    SemanticCacheRecallConfig,
    SemanticCacheWriteConfig,
    ZeusEndpointConfig,
)
from zeus_client.domain.messages import TurnRequest, TurnStatus
from zeus_client.ports import LlmResponse
from zeus_client.ports.agent_memory import RecalledBlock, RecallResult, WriteResult


@dataclass
class ScriptedMemory:
    recall_result: RecallResult | None = None
    write_result: WriteResult | None = None
    recalls: list[dict[str, Any]] = field(default_factory=list)
    writes: list[dict[str, Any]] = field(default_factory=list)
    available_flag: bool = True

    async def available(self) -> bool:
        return self.available_flag

    async def status(self):
        from zeus_client.ports.agent_memory import AgentMemoryStatus

        return AgentMemoryStatus(enabled=self.available_flag)

    async def recall(self, query: str, **kwargs: Any) -> RecallResult:
        self.recalls.append({"query": query, **kwargs})
        if self.recall_result is None:
            return RecallResult(ok=True, status_code=200, blocks=())
        return self.recall_result

    async def write_block(self, text: str, **kwargs: Any) -> WriteResult:
        self.writes.append({"text": text, **kwargs})
        if self.write_result is None:
            return WriteResult(ok=True, status_code=201, block_id="amb_x")
        return self.write_result


def _on_cfg(**kwargs: Any) -> SemanticCacheConfig:
    return SemanticCacheConfig(enabled=True, **kwargs)


@pytest.mark.asyncio
async def test_flag_off_zero_memory_calls() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="Hello.", tool_calls=())])
    mem = ScriptedMemory()
    result = await run_agent_turn(
        TurnRequest(message="hello there friend", tools=()),
        llm=llm,
        agent_memory=mem,
        semantic_cache=SemanticCacheConfig(enabled=False),
    )
    assert result.status is TurnStatus.OK
    assert mem.recalls == []
    assert mem.writes == []
    assert llm.calls[0].messages[0]["content"].count("semantic_memory:") == 0


@pytest.mark.asyncio
async def test_flag_on_injects_before_first_llm() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="Using memory.", tool_calls=())])
    mem = ScriptedMemory(
        recall_result=RecallResult(
            ok=True,
            status_code=200,
            req_id="req-mem",
            url="http://z/v2/agent_memory/recall",
            blocks=(
                RecalledBlock(
                    block_id="amb_1",
                    type="profile",
                    text="prefers nonstop flights",
                    summary="short nonstop",
                    score=0.9,
                ),
            ),
        )
    )
    result = await run_agent_turn(
        TurnRequest(message="find cheap nonstop flights please", tools=()),
        llm=llm,
        agent_memory=mem,
        semantic_cache=_on_cfg(),
    )
    assert result.status is TurnStatus.OK
    assert len(mem.recalls) == 1
    sys_msg = str(llm.calls[0].messages[0]["content"])
    assert "semantic_memory:" in sys_msg
    assert "short nonstop" in sys_msg
    assert any(h.get("name") == "agent_memory.recall" for h in result.debug.hops)
    assert mem.writes == []  # write_explicit_only default


@pytest.mark.asyncio
async def test_recall_fail_open_continues() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="Still answered.", tool_calls=())])
    mem = ScriptedMemory(
        recall_result=RecallResult(
            ok=False,
            status_code=503,
            error="store_unavailable",
            skip_reason="error",
            url="http://z/v2/agent_memory/recall",
        )
    )
    result = await run_agent_turn(
        TurnRequest(message="find cheap nonstop flights please", tools=()),
        llm=llm,
        agent_memory=mem,
        semantic_cache=_on_cfg(),
    )
    assert result.status is TurnStatus.OK
    assert result.answer == "Still answered."
    assert "semantic_memory:" not in str(llm.calls[0].messages[0]["content"])


@pytest.mark.asyncio
async def test_fail_closed_aborts_turn() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="should not run", tool_calls=())])
    mem = ScriptedMemory(
        recall_result=RecallResult(
            ok=False, status_code=503, error="no_embedder", skip_reason="error"
        )
    )
    result = await run_agent_turn(
        TurnRequest(message="find cheap nonstop flights please", tools=()),
        llm=llm,
        agent_memory=mem,
        semantic_cache=_on_cfg(recall=SemanticCacheRecallConfig(fail_closed=True)),
    )
    assert result.status is TurnStatus.ERROR
    assert result.error is not None
    assert result.error.code == "040008"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_min_query_chars_skips_http() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="ok", tool_calls=())])
    mem = ScriptedMemory()
    await run_agent_turn(
        TurnRequest(message="hi", tools=()),
        llm=llm,
        agent_memory=mem,
        semantic_cache=_on_cfg(),
    )
    assert mem.recalls == []


@pytest.mark.asyncio
async def test_auto_write_user_message_when_not_explicit_only() -> None:
    llm = ScriptedLlm(script=[LlmResponse(content="Noted.", tool_calls=())])
    mem = ScriptedMemory()
    msg = "I prefer nonstop flights under six hours"
    result = await run_agent_turn(
        TurnRequest(message=msg, tools=()),
        llm=llm,
        agent_memory=mem,
        semantic_cache=_on_cfg(
            write=SemanticCacheWriteConfig(
                write_explicit_only=False,
                write_user_message=True,
                min_chars=24,
            )
        ),
    )
    assert result.status is TurnStatus.OK
    assert len(mem.writes) == 1
    assert mem.writes[0]["text"] == msg


@pytest.mark.asyncio
@respx.mock
async def test_typeahead_never_hits_agent_memory() -> None:
    base = "http://zeus.test:8080"
    mem_r = respx.post(f"{base}/v2/agent_memory/recall").mock(
        return_value=httpx.Response(200, json={"blocks": []})
    )
    write_r = respx.post(f"{base}/v2/agent_memory/blocks").mock(
        return_value=httpx.Response(201, json={"block_id": "x"})
    )
    respx.post(f"{base}/v2/yelp-data/_default/_default/search").mock(
        return_value=httpx.Response(
            200,
            json={"result": {"src_keys": ["biz:1"], "items": [{"node": {"name": "Sushi"}}]}},
        )
    )
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url=base, auth_mode="none"),
        semantic_cache=_on_cfg(),
        target=DataTarget(bucket="yelp-data", scope="_default", collection="_default"),
    )
    port = HttpxZeusPort(endpoint=cfg.zeus, secrets=EnvSecretStore(environ={}), turn_id="t")
    await run_typeahead_search(port, "sushi", target=cfg.target, options=SuggestOptions(limit=4))
    assert mem_r.call_count == 0
    assert write_r.call_count == 0
    await port.aclose()
