"""JobsAPI fail-closed + FakeJobRuntime L4 seed (ZCP-72)."""

from __future__ import annotations

import pytest

from zeus_client.adapters.jobs_fake import FakeJobRuntime
from zeus_client.config.models import (
    ClientSettings,
    DataTarget,
    LlmProviderConfig,
    LlmRoleConfig,
    RuntimeConfig,
)
from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import UnitConfig, UnitKind
from zeus_client.ports import LlmRequest, LlmResponse, VerbHopResult, VerbRequest
from zeus_client.runtime import ZeusRuntime


class RecordingZeus:
    def __init__(self) -> None:
        self.calls: list[VerbRequest] = []

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.calls.append(req)
        return VerbHopResult(ok=True, status_code=200, req_id=f"req-{req.target.bucket}", body={})


def _direct(unit_id: str, bucket: str, *, verb: str = "find") -> UnitConfig:
    return UnitConfig(
        unit_id=unit_id,
        kind=UnitKind.ZEUS_DIRECT,
        goal=f"scan {bucket}",
        zeus_url="http://127.0.0.1:8080",
        bucket=bucket,
        scope="sales",
        collection="_default",
        call={"verb": verb, "body": {"entity_type": "Beer"}},
    )


@pytest.mark.asyncio
async def test_jobs_unavailable_without_host() -> None:
    async with ZeusRuntime(RuntimeConfig(), zeus=RecordingZeus()) as rt:
        with pytest.raises(JobError) as ei:
            await rt.jobs.run(
                "fan-out",
                units=[_direct("u1", "east")],
            )
    assert ei.value.code is ErrorCode.JOBS_UNAVAILABLE


@pytest.mark.asyncio
async def test_fake_job_two_targets_and_monotonic_seq() -> None:
    zeus = RecordingZeus()
    rt = ZeusRuntime(RuntimeConfig(target=DataTarget(bucket="west")), zeus=zeus)
    rt.services.jobs = FakeJobRuntime(rt)
    async with rt:
        handle = await rt.jobs.run(
            "two scopes",
            units=[_direct("u1", "east"), _direct("u2", "north")],
        )
        events = [ev async for ev in rt.jobs.watch(handle.job_id)]
        snap = await rt.jobs.get(handle.job_id)
    assert [c.target.bucket for c in zeus.calls] == ["east", "north"]
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))
    assert events[0].type == "job.started"
    assert events[-1].type == "job.finished"
    assert snap.status == "ok"
    assert snap.partial is False


@pytest.mark.asyncio
async def test_fake_job_partial_on_one_unit_error() -> None:
    zeus = RecordingZeus()
    rt = ZeusRuntime(RuntimeConfig(), zeus=zeus)
    rt.services.jobs = FakeJobRuntime(rt)
    async with rt:
        handle = await rt.jobs.run(
            "partial",
            units=[_direct("u1", "east", verb="pipeline"), _direct("u2", "north")],
        )
        snap = await rt.jobs.get(handle.job_id)
        events = [ev async for ev in rt.jobs.watch(handle.job_id)]
    assert snap.partial is True
    assert snap.status == "partial"
    assert {s["status"] for s in snap.unit_summaries} == {"error", "ok"}
    assert any(e.type == "job.finished" for e in events)


@pytest.mark.asyncio
async def test_fake_job_forwards_unit_models_to_agent_turn() -> None:
    class _Llm:
        def __init__(self) -> None:
            self.calls: list[LlmRequest] = []

        async def complete(self, req: LlmRequest) -> LlmResponse:
            self.calls.append(req)
            return LlmResponse(content="ok", tool_calls=())

    llm = _Llm()
    zeus = RecordingZeus()
    cfg = RuntimeConfig(
        target=DataTarget(bucket="west", scope="s", collection="c"),
        llm=LlmProviderConfig(
            model="fast-worker",
            api_key_env="LLM_DEFAULT_KEY",
            roles={"worker": LlmRoleConfig(model="fast-worker", api_key_env="LLM_DEFAULT_KEY")},
        ),
        settings=ClientSettings(durable_sessions=False),
    )
    rt = ZeusRuntime(cfg, llm=llm, zeus=zeus)
    rt.services.jobs = FakeJobRuntime(rt)
    unit = UnitConfig(
        unit_id="u1",
        kind=UnitKind.AGENT_TURN,
        goal="shortlist fruit beers",
        zeus_url="http://127.0.0.1:8080",
        bucket="beer-sample",
        scope="sales",
        collection="_default",
        catalog_mode="analytics",
        chat_request={"messages": [{"role": "system", "content": "## SCOPE BRIEF\nscope: b/s\n"}]},
    )
    async with rt:
        await rt.jobs.run(
            "fan-out",
            units=[unit],
            models={"units": {"u1": {"model": "fast-worker-v3"}}},
        )
    assert llm.calls
    assert llm.calls[0].model == "fast-worker-v3"


@pytest.mark.asyncio
async def test_fake_job_cancel_sets_status() -> None:
    zeus = RecordingZeus()
    rt = ZeusRuntime(RuntimeConfig(), zeus=zeus)
    fake = FakeJobRuntime(rt)
    rt.services.jobs = fake
    async with rt:
        handle = await rt.jobs.run("cancel-me", units=[_direct("u1", "east")])
        snap = await rt.jobs.cancel(handle.job_id)
    assert snap.status == "cancelled"
