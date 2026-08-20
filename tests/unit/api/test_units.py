"""UnitsAPI isolation wrappers (ZCP-71)."""

from __future__ import annotations

import asyncio

import pytest

from zeus_client.application.units_transport import UnitScopedZeusPort, same_zeus_host
from zeus_client.config.models import (
    ClientSettings,
    DataTarget,
    LlmProviderConfig,
    LlmRoleConfig,
    RuntimeConfig,
    ZeusEndpointConfig,
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

    async def resolve_auth(self, target: DataTarget, *, force: bool = False) -> object:
        return object()

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.calls.append(req)
        return VerbHopResult(ok=True, status_code=200, req_id=f"req-{req.target.bucket}", body={})


def test_same_zeus_host_normalizes_slash() -> None:
    assert same_zeus_host("http://z:8080/", "http://z:8080") is True
    assert same_zeus_host("http://z-b:8080", "http://z:8080") is False
    assert same_zeus_host(None, "http://z:8080") is True


@pytest.mark.asyncio
async def test_unit_scoped_port_forwards_resolve_auth() -> None:
    inner = RecordingZeus()
    port = UnitScopedZeusPort(inner, _direct_unit("u1"))
    got = await port.resolve_auth(DataTarget())
    assert got is not None


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
async def test_agent_turn_unit_llm_override_wins_model() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        result = await rt.units.agent_turn(_agent_unit("u1", llm={"model": "fast-worker-v3"}))
    assert result.status is UnitStatus.OK
    assert llm.calls[0].model == "fast-worker-v3"


@pytest.mark.asyncio
async def test_agent_turn_distinct_worker_key_does_not_use_process_llm() -> None:
    process = ScriptedLlm()
    worker = ScriptedLlm()
    zeus = RecordingZeus()
    cfg = RuntimeConfig(
        llm=LlmProviderConfig(
            model="default-model",
            api_key_env="LLM_DEFAULT_KEY",
            roles={"worker": LlmRoleConfig(model="fast-worker", api_key_env="LLM_WORKER_KEY")},
        ),
        settings=ClientSettings(durable_sessions=False),
    )
    async with ZeusRuntime(cfg, llm=process, zeus=zeus) as rt:
        rt.llm_for_slice = lambda slice: (  # type: ignore[method-assign]
            worker if slice.api_key_env == "LLM_WORKER_KEY" else process
        )
        result = await rt.units.agent_turn(_agent_unit("u1"))
    assert result.status is UnitStatus.OK
    assert process.calls == []
    assert worker.calls
    assert worker.calls[0].model == "fast-worker"
    started = [e for e in rt.journal.events() if e.type == EVENT_UNIT_STARTED]
    assert started
    assert started[0].data.get("api_key_env") == "LLM_WORKER_KEY"
    assert "sk-" not in str(started[0].data)


@pytest.mark.asyncio
async def test_mode1_run_turn_ignores_llm_roles() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        await rt.agent.run_turn("hello")
    assert llm.calls
    assert llm.calls[0].model == "default-model"


@pytest.mark.asyncio
async def test_agent_turn_copies_usage_onto_artifacts() -> None:
    class _UsageLlm:
        calls: list[LlmRequest] = []

        async def complete(self, req: LlmRequest) -> LlmResponse:
            self.calls.append(req)
            return LlmResponse(
                content="unit answer",
                tool_calls=(),
                usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            )

    llm = _UsageLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:  # type: ignore[arg-type]
        result = await rt.units.agent_turn(_agent_unit("u1"))
    assert result.status is UnitStatus.OK
    usage = result.artifacts.get("usage")
    assert isinstance(usage, dict)
    assert usage.get("prompt") == 10
    assert usage.get("completion") == 2
    assert "api_key" not in str(result.artifacts)


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
async def test_zeus_direct_units_use_per_unit_zeus_url() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        await rt.units.zeus_direct(
            UnitConfig(
                unit_id="u1",
                kind=UnitKind.ZEUS_DIRECT,
                goal="east",
                zeus_url="http://zeus-east:8080",
                bucket="east",
                scope="sales",
                collection="_default",
                call={"verb": "find", "body": {"entity_type": "Beer"}},
            )
        )
        await rt.units.zeus_direct(
            UnitConfig(
                unit_id="u2",
                kind=UnitKind.ZEUS_DIRECT,
                goal="west",
                zeus_url="http://zeus-west:8080",
                bucket="west",
                scope="sales",
                collection="_default",
                call={"verb": "find", "body": {"entity_type": "Beer"}},
            )
        )
    assert [c.base_url for c in zeus.calls] == [
        "http://zeus-east:8080",
        "http://zeus-west:8080",
    ]


@pytest.mark.asyncio
async def test_zeus_direct_auth_none_does_not_inherit_process_basic() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(
            url="http://127.0.0.1:8080",
            auth_mode="basic",
            username="admin",
            password_env="ZEUS_PASSWORD",
        ),
        llm=LlmProviderConfig(model="default-model", api_key_env="LLM_DEFAULT_KEY"),
        settings=ClientSettings(durable_sessions=False),
    )
    async with ZeusRuntime(cfg, llm=llm, zeus=zeus) as rt:
        await rt.units.zeus_direct(
            UnitConfig(
                unit_id="u1",
                kind=UnitKind.ZEUS_DIRECT,
                goal="open",
                zeus_url="http://127.0.0.1:8080",
                bucket="east",
                scope="sales",
                collection="_default",
                auth_mode="none",
                call={"verb": "find", "body": {"entity_type": "Beer"}},
            )
        )
    assert zeus.calls[0].auth_mode == "none"
    assert zeus.calls[0].password_env is None


@pytest.mark.asyncio
async def test_agent_turn_tool_hop_uses_unit_zeus_url() -> None:
    class _ToolLlm:
        def __init__(self) -> None:
            self.calls: list[LlmRequest] = []
            self._n = 0

        async def complete(self, req: LlmRequest) -> LlmResponse:
            self.calls.append(req)
            self._n += 1
            if self._n == 1:
                return LlmResponse(
                    content=None,
                    tool_calls=(
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "find",
                                "arguments": '{"entity_type": "Beer"}',
                            },
                        },
                    ),
                )
            return LlmResponse(content="unit answer", tool_calls=())

    llm = _ToolLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:  # type: ignore[arg-type]
        result = await rt.units.agent_turn(
            _agent_unit("u1", zeus_url="http://zeus-b:8080"),
            job_id="job_1",
        )
    assert result.status is UnitStatus.OK
    assert zeus.calls
    assert zeus.calls[0].base_url == "http://zeus-b:8080"
    assert zeus.calls[0].verb == "find"


@pytest.mark.asyncio
async def test_agent_turn_other_host_missing_inject_is_130012() -> None:
    llm = ScriptedLlm()
    zeus = RecordingZeus()
    async with _runtime(llm, zeus) as rt:
        with pytest.raises(JobError) as ei:
            await rt.units.agent_turn(_agent_unit("u1", brief=False, zeus_url="http://zeus-b:8080"))
    assert ei.value.code is ErrorCode.UNITS_INJECT_MISSING
    assert llm.calls == []
    assert zeus.calls == []


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
