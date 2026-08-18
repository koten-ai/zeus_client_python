"""DataAPI per-call DataTarget + Rewind header passthrough (ZCP-70)."""

from __future__ import annotations

import pytest

from zeus_client.adapters.zeus_http.headers import TRACE_CLASS_DIRECT_READ
from zeus_client.config.models import DataTarget, RuntimeConfig
from zeus_client.ports import VerbHopResult, VerbRequest
from zeus_client.runtime import ZeusRuntime


class _RecordingZeus:
    def __init__(self) -> None:
        self.reqs: list[VerbRequest] = []

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.reqs.append(req)
        return VerbHopResult(ok=True, status_code=200, req_id="req_east", body={"ok": True})


@pytest.mark.asyncio
async def test_data_verb_optional_target_does_not_mutate_config() -> None:
    zeus = _RecordingZeus()
    cfg = RuntimeConfig(target=DataTarget(bucket="west", scope="s", collection="c"))
    async with ZeusRuntime(cfg, zeus=zeus) as rt:
        east = DataTarget(bucket="east", scope="sales", collection="_default")
        result = await rt.data.find({"entity_type": "Beer"}, target=east)
    assert result.ok is True
    assert len(zeus.reqs) == 1
    assert zeus.reqs[0].target.bucket == "east"
    assert zeus.reqs[0].target != cfg.target
    assert rt.config.target.bucket == "west"
    assert zeus.reqs[0].headers.get("X-Zeus-Trace-Class") == TRACE_CLASS_DIRECT_READ


@pytest.mark.asyncio
async def test_data_verb_default_target_is_runtime_config() -> None:
    zeus = _RecordingZeus()
    cfg = RuntimeConfig(target=DataTarget(bucket="west", scope="s", collection="c"))
    async with ZeusRuntime(cfg, zeus=zeus) as rt:
        await rt.data.find({"entity_type": "Beer"})
    assert zeus.reqs[0].target.bucket == "west"


@pytest.mark.asyncio
async def test_data_verb_forwards_rewind_chat_headers() -> None:
    zeus = _RecordingZeus()
    async with ZeusRuntime(RuntimeConfig(), zeus=zeus) as rt:
        await rt.data.verb(
            "find",
            {"entity_type": "Beer"},
            chat_id="job_1",
            turn_id="unit_u1",
        )
    headers = zeus.reqs[0].headers
    assert headers["X-Zeus-Chat-Id"] == "job_1"
    assert headers["X-Zeus-Turn-Id"] == "unit_u1"
    assert headers["X-Zeus-Trace-Class"] == TRACE_CLASS_DIRECT_READ
    assert "X-Zeus-Req-Id" not in headers
