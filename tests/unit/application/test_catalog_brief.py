"""Live SCOPE BRIEF borrow (hash-excluded inject)."""

from __future__ import annotations

import pytest

from zeus_client.api.agent import AgentAPI
from zeus_client.application.catalog_brief import (
    ensure_scope_brief,
    live_mode_candidates,
)
from zeus_client.config.models import (
    ClientSettings,
    DataTarget,
    DebugPolicy,
    LlmProviderConfig,
    RuntimeConfig,
    ZeusEndpointConfig,
)
from zeus_client.ports import LlmRequest, LlmResponse
from zeus_client.runtime import Services, ZeusRuntime

LIVE = {
    "messages": [
        {
            "content": (
                "## SCOPE BRIEF\n"
                "scope: travel-sample/_default\n\n"
                "## MINI-SCHEMA\n"
                "### Airport  (fields: 2)\n"
                "  - country               scalar_ent   [gsi]\n"
            )
        }
    ]
}


@pytest.mark.asyncio
async def test_ensure_merges_when_missing() -> None:
    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        assert bucket == "travel-sample"
        assert scope == "_default"
        assert mode in {"analytics_v2_base_6", "analytics"}
        return LIVE

    out = await ensure_scope_brief(
        {"messages": [{"role": "system", "content": "LOCKED RULES"}]},
        fetch=fetch,
        bucket="travel-sample",
        scope="_default",
        mode="analytics_v2_base_6",
    )
    assert out.merged is True
    content = out.body["messages"][0]["content"]
    assert content.startswith("LOCKED RULES")
    assert "## SCOPE BRIEF" in content
    assert "## MINI-SCHEMA" in content
    assert "Airport" in content
    assert out.note == "scope_brief: live merge"


@pytest.mark.asyncio
async def test_ensure_skips_when_already_present() -> None:
    calls = 0

    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        nonlocal calls
        calls += 1
        return LIVE

    doc = {"messages": [{"role": "system", "content": "rules\n\n## SCOPE BRIEF\nold"}]}
    out = await ensure_scope_brief(doc, fetch=fetch, bucket="b", scope="s", mode="analytics")
    assert out.merged is False
    assert calls == 0
    assert out.note == "scope_brief: already present"
    assert out.body["messages"][0]["content"] == "rules\n\n## SCOPE BRIEF\nold"


@pytest.mark.asyncio
async def test_ensure_no_remote_is_noop() -> None:
    out = await ensure_scope_brief(
        {"messages": [{"role": "system", "content": "rules"}]},
        fetch=None,
        bucket="b",
        scope="s",
        mode="analytics",
    )
    assert out.merged is False
    assert "no catalog_remote" in out.note


@pytest.mark.asyncio
async def test_ensure_fetch_error_is_nonfatal() -> None:
    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        raise RuntimeError("down")

    out = await ensure_scope_brief(
        {"messages": [{"role": "system", "content": "rules"}]},
        fetch=fetch,
        bucket="b",
        scope="s",
        mode="analytics",
    )
    assert out.merged is False
    assert "live fetch failed" in out.note
    assert out.body["messages"][0]["content"] == "rules"


@pytest.mark.asyncio
async def test_ensure_live_without_marker_is_noop() -> None:
    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        return {"messages": [{"content": "no markers here"}]}

    out = await ensure_scope_brief(
        {"messages": [{"role": "system", "content": "rules"}]},
        fetch=fetch,
        bucket="b",
        scope="s",
        mode="analytics",
    )
    assert out.merged is False
    assert "no SCOPE BRIEF" in out.note


def test_live_mode_candidates_adds_family() -> None:
    assert live_mode_candidates("analytics_v2_base_6") == (
        "analytics_v2_base_6",
        "analytics",
    )
    assert live_mode_candidates("analytics") == ("analytics",)


def test_live_mode_candidates_stem_named_stamped_uses_analytics() -> None:
    stamped = "mode_v2_base-6.1_analytics_stamped"
    names = live_mode_candidates(stamped)
    assert names[0] == stamped
    assert "analytics" in names
    assert "mode" not in names
    assert live_mode_candidates(stamped, lineage_mode="analytics") == (
        stamped,
        "analytics",
    )


@pytest.mark.asyncio
async def test_ensure_retries_family_mode_when_long_mode_empty() -> None:
    seen: list[str] = []

    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        seen.append(mode)
        if mode == "analytics":
            return LIVE
        return {"messages": [{"content": "no brief"}]}

    out = await ensure_scope_brief(
        {"messages": [{"role": "system", "content": "LOCKED"}]},
        fetch=fetch,
        bucket="travel-sample",
        scope="_default",
        mode="analytics_v2_base_6",
    )
    assert seen == ["analytics_v2_base_6", "analytics"]
    assert out.merged is True
    assert "mode=analytics" in out.note


@pytest.mark.asyncio
async def test_ensure_stem_named_mode_does_not_fetch_family_mode() -> None:
    seen: list[str] = []

    async def fetch(bucket: str, scope: str, mode: str) -> dict:
        seen.append(mode)
        if mode == "analytics":
            return LIVE
        raise RuntimeError(f"chat_request HTTP 404: pinned chat_request not found for mode={mode}")

    out = await ensure_scope_brief(
        {
            "messages": [{"role": "system", "content": "LOCKED"}],
            "_lineage": {"base_id": "base-6.1", "mode": "analytics"},
        },
        fetch=fetch,
        bucket="travel-sample",
        scope="_default",
        mode="mode_v2_base-6.1_analytics_stamped",
    )
    assert "mode" not in seen
    assert seen[0] == "mode_v2_base-6.1_analytics_stamped"
    assert "analytics" in seen
    assert out.merged is True
    assert "## SCOPE BRIEF" in out.body["messages"][0]["content"]
    assert "## MINI-SCHEMA" in out.body["messages"][0]["content"]


class _ScriptedLlm:
    def __init__(self) -> None:
        self.calls: list[LlmRequest] = []

    async def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls.append(req)
        return LlmResponse(content="SFO, JFK, ORD", tool_calls=())


class _LiveRemote:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.last_req_id = "req-live-brief"

    async def fetch_chat_request(
        self, bucket: str, scope: str, mode: str, **kwargs: object
    ) -> dict:
        self.calls.append((bucket, scope, mode))
        return LIVE


@pytest.mark.asyncio
async def test_agent_run_turn_merges_brief_into_system() -> None:
    llm = _ScriptedLlm()
    remote = _LiveRemote()
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url="http://host.docker.internal:8080"),
        llm=LlmProviderConfig(provider="test", base_url="http://llm", model="m"),
        target=DataTarget(bucket="travel-sample", scope="_default"),
        settings=ClientSettings(ai_process_result=False, mode="analytics_v2_base_6"),
        debug=DebugPolicy(detective_briefing=True),
    )
    svc = Services()
    svc.llm = llm
    svc.catalog_remote = remote
    api = AgentAPI(ZeusRuntime(cfg, services=svc))
    result = await api.run_turn(
        "Give me the list of airports in US",
        chat_request={"messages": [{"role": "system", "content": "LOCKED RULES"}]},
        enable_sessions=False,
    )
    assert result.status.value == "ok"
    assert remote.calls == [("travel-sample", "_default", "analytics_v2_base_6")]
    system = llm.calls[0].messages[0]["content"]
    assert "## SCOPE BRIEF" in system
    assert "## MINI-SCHEMA" in system
    det = result.debug.detective or {}
    prompt = det.get("prompt") or {}
    inject = prompt.get("inject") or {}
    assert inject.get("has_scope_brief") is True
    assert inject.get("has_mini_schema") is True
    assert prompt.get("verdict") != "fail"
    assert any("scope_brief: live merge" in n for n in result.debug.notes)


class _AnalyticsOnlyRemote:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.last_req_id = "req-live-brief"

    async def fetch_chat_request(
        self, bucket: str, scope: str, mode: str, **kwargs: object
    ) -> dict:
        self.calls.append((bucket, scope, mode))
        if mode != "analytics":
            raise RuntimeError(
                f"chat_request HTTP 404: pinned chat_request not found for mode={mode}"
            )
        return LIVE


@pytest.mark.asyncio
async def test_agent_run_turn_merges_brief_for_stem_named_mode() -> None:
    llm = _ScriptedLlm()
    remote = _AnalyticsOnlyRemote()
    stamped = "mode_v2_base-6.1_analytics_stamped"
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url="http://host.docker.internal:8080"),
        llm=LlmProviderConfig(provider="test", base_url="http://llm", model="m"),
        target=DataTarget(bucket="travel-sample", scope="_default"),
        settings=ClientSettings(ai_process_result=False, mode=stamped),
        debug=DebugPolicy(detective_briefing=True),
        client_floor="client-floor-6.1",
    )
    svc = Services()
    svc.llm = llm
    svc.catalog_remote = remote
    api = AgentAPI(ZeusRuntime(cfg, services=svc))
    result = await api.run_turn(
        "Give me the list of airports in US",
        chat_request={
            "messages": [{"role": "system", "content": "LOCKED RULES"}],
            "_lineage": {"base_id": "base-6.1", "mode": "analytics"},
        },
        enable_sessions=False,
    )
    assert result.status.value == "ok"
    assert [c[2] for c in remote.calls] == [stamped, "analytics"]
    assert "mode" not in [c[2] for c in remote.calls]
    system = llm.calls[0].messages[0]["content"]
    assert "## SCOPE BRIEF" in system
    assert "## MINI-SCHEMA" in system
    det = result.debug.detective or {}
    prompt = det.get("prompt") or {}
    inject = prompt.get("inject") or {}
    assert inject.get("has_scope_brief") is True
    assert inject.get("has_mini_schema") is True
    assert prompt.get("verdict") != "fail"
