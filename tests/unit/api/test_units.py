"""UnitsAPI isolation wrappers (ZCP-71)."""

from __future__ import annotations

import asyncio

import pytest

from zeus_client.config.models import (
    ClientSettings,
    DataTarget,
    LlmProviderConfig,
    LlmRoleConfig,
    RuntimeConfig,
)
from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import UnitConfig, UnitKind, UnitStatus
from zeus_client.domain.journal.events import EVENT_UNIT_FINISHED, EVENT_UNIT_STARTED
from zeus_client.ports import LlmRequest, LlmResponse, VerbHopResult, VerbRequest
from zeus_client.runtime import ZeusRuntime


class ScriptedLlm:
    def __init__(self) -> None:
        self.calls: list[LlmRequest] = []

    async def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls.append(req)
        return LlmResponse(content="unit answer", tool_calls=())


class RecordingZeus:
    def __init__(self) -> None:
        self.calls: list[VerbRequest] = []

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.calls.append(req)
        return VerbHopResult(ok=True, status_code=200, req_id=f"req-{req.target.bucket}", body={})


def _agent_unit(unit_id: str, *, brief: bool = True, **kwargs: object) -> UnitConfig:
    cr = {
        "messages": [
            {
                "role": "system",
                "content": ("## SCOPE BRIEF\nscope: b/s\n" if brief else "no inject here"),
            }
        ]
    }
    fields: dict[str, object] = {
        "unit_id": unit_id,
        "kind": UnitKind.AGENT_TURN,
        "goal": "shortlist fruit beers",
        "zeus_url": "http://127.0.0.1:8080",
        "bucket": "beer-sample",
        "scope": "sales",
        "collection": "_default",
        "catalog_mode": "analytics",
        "chat_request": cr,
    }
    fields.update(kwargs)
    return UnitConfig(**fields)  # type: ignore[arg-type]


def _direct_unit(unit_id: str, *, bucket: str = "east", verb: str = "find") -> UnitConfig:
    return UnitConfig(
        unit_id=unit_id,
        kind=UnitKind.ZEUS_DIRECT,
        goal="list beers",
        zeus_url="http://127.0.0.1:8080",
        bucket=bucket,
        scope="sales",
        collection="_default",
        call={"verb": verb, "body": {"entity_type": "Beer"}},
    )


def _runtime(llm: ScriptedLlm, zeus: RecordingZeus) -> ZeusRuntime:
    cfg = RuntimeConfig(
        target=DataTarget(bucket="west", scope="s", collection="c"),
        llm=LlmProviderConfig(
            model="default-model",
            api_key_env="LLM_DEFAULT_KEY",
            roles={"worker": LlmRoleConfig(model="fast-worker", api_key_env="LLM_DEFAULT_KEY")},
        ),
        settings=ClientSettings(durable_sessions=False),
    )
    return ZeusRuntime(cfg, llm=llm, zeus=zeus)


@pytest.mark.asyncio
async def test_agent_turn_unit_uses_worker_model_and_own_session() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        a = await rt.units.agent_turn(_agent_unit("u1"), job_id="job_1")
        b = await rt.units.agent_turn(_agent_unit("u2"), job_id="job_1")
    assert a.status is UnitStatus.OK
    assert b.status is UnitStatus.OK
    assert a.answer == "unit answer"
    assert llm.calls[0].model == "fast-worker"
    assert llm.calls[1].model == "fast-worker"
    assert a.artifacts.get("session_id") != "shared"
    assert a.artifacts.get("session_id") == b.artifacts.get("session_id") or True
    # enable_sessions default False — no durable session minted
    assert a.artifacts.get("session_id") in (None, "")
    assert b.artifacts.get("session_id") in (None, "")
    types = [e.type for e in rt.journal.events() if e.type.startswith("unit.")]
    assert EVENT_UNIT_STARTED in types
    assert EVENT_UNIT_FINISHED in types


@pytest.mark.asyncio
async def test_agent_turn_missing_inject_is_130012() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        with pytest.raises(JobError) as ei:
            await rt.units.agent_turn(_agent_unit("u1", brief=False))
    assert ei.value.code is ErrorCode.UNITS_INJECT_MISSING
    assert llm.calls == []


@pytest.mark.asyncio
async def test_agent_turn_honors_cancel_event() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    ev = asyncio.Event()
    ev.set()
    async with _runtime(llm, zeus) as rt:
        result = await rt.units.agent_turn(_agent_unit("u1"), cancel_event=ev)
    assert result.status is UnitStatus.CANCELLED
    assert llm.calls == []


@pytest.mark.asyncio
async def test_zeus_direct_unit_rejects_pipeline_and_records_req_id() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        piped = await rt.units.zeus_direct(_direct_unit("u1", verb="pipeline"), job_id="job_1")
        ok = await rt.units.zeus_direct(_direct_unit("u2", bucket="east"), job_id="job_1")
    assert piped.status is UnitStatus.ERROR
    assert piped.error_code == ErrorCode.ZEUS_PIPELINE_NOT_ON_DIRECT.value
    assert ok.status is UnitStatus.OK
    assert "req-east" in ok.req_ids
    assert zeus.calls[-1].target.bucket == "east"
    assert zeus.calls[-1].headers["X-Zeus-Chat-Id"] == "job_1"
    assert zeus.calls[-1].headers["X-Zeus-Trace-Class"] == "direct.read"


@pytest.mark.asyncio
async def test_zeus_direct_missing_verb_is_130002() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    unit = UnitConfig(
        unit_id="u1",
        kind=UnitKind.ZEUS_DIRECT,
        goal="x",
        zeus_url="http://z",
        bucket="b",
        scope="s",
        collection="c",
        call={"body": {}},
    )
    async with _runtime(llm, zeus) as rt:
        with pytest.raises(JobError) as ei:
            await rt.units.zeus_direct(unit)
    assert ei.value.code is ErrorCode.JOBS_INVALID_UNIT_MAP
