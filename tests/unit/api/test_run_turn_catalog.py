"""ZDM-44: a missing catalog is an error, not an ungrounded answer."""

from __future__ import annotations

from pathlib import Path

import pytest

from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.api.agent import AgentAPI
from zeus_client.config.models import (
    ClientSettings,
    DataTarget,
    LlmProviderConfig,
    RuntimeConfig,
    ZeusEndpointConfig,
)
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.ports import LlmRequest, LlmResponse
from zeus_client.runtime import Services, ZeusRuntime


class _ScriptedLlm:
    def __init__(self) -> None:
        self.calls: list[LlmRequest] = []

    async def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls.append(req)
        return LlmResponse(content="from general knowledge", tool_calls=())


def _runtime(tmp_path: Path, llm: _ScriptedLlm) -> ZeusRuntime:
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url="http://127.0.0.1:8080"),
        llm=LlmProviderConfig(provider="test", base_url="http://llm", model="m"),
        target=DataTarget(bucket="beer-sample", scope="_default"),
        settings=ClientSettings(
            mode="analytics",
            durable_sessions=False,
            ai_process_result=False,
        ),
        chat_requests_dir=str(tmp_path),
        client_floor="client-floor-6.1",
    )
    svc = Services()
    svc.llm = llm
    svc.catalog = FsCatalogStore(root=tmp_path)
    return ZeusRuntime(cfg, services=svc)


@pytest.mark.asyncio
async def test_run_turn_raises_when_the_catalog_is_missing(tmp_path: Path) -> None:
    llm = _ScriptedLlm()
    api = AgentAPI(_runtime(tmp_path, llm))
    with pytest.raises(CatalogError) as ei:
        await api.run_turn("What beers are made from Peaches?")
    assert ei.value.code == ErrorCode.CATALOG_NOT_FOUND
    assert llm.calls == []


@pytest.mark.asyncio
async def test_run_turn_loads_the_scope_catalog_without_base_id(tmp_path: Path) -> None:
    scope = tmp_path / "beer-sample__default"
    scope.mkdir()
    (scope / "chat_request_analytics_v2.json").write_text(
        '{"_format":"zeus.chat_request.v2","_lineage":{"base_id":"base-6.1"},'
        '"messages":[{"role":"system","content":"## SCOPE BRIEF\\nbeer\\n## MINI-SCHEMA\\nBeer"}],'
        '"verbs":[]}\n',
        encoding="utf-8",
    )
    llm = _ScriptedLlm()
    api = AgentAPI(_runtime(tmp_path, llm))
    result = await api.run_turn("What beers are made from Peaches?")
    assert result.status.value == "ok"
    assert llm.calls
    system = llm.calls[0].messages[0]["content"]
    assert "## MINI-SCHEMA" in system
    assert "from general knowledge" in (result.answer or "")
