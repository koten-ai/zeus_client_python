"""Contract tests for Pattern B HTTP/SSE WatchJob (ZCP-73)."""

from __future__ import annotations

import httpx
import pytest
import respx

from zeus_client.adapters.jobs_http.client import HttpxJobRuntime
from zeus_client.adapters.jobs_http.paths import FROM_SEQ_PARAM, events_url
from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.runtime import ZeusRuntime

HOST = "http://jobs.test:7090"


def _sse(*payloads: str) -> str:
    return "".join(f"data: {p}\n\n" for p in payloads)


@pytest.mark.asyncio
@respx.mock
async def test_watch_sse_from_seq_and_order() -> None:
    url = events_url(HOST, "j1")
    route = respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text=_sse(
                '{"seq":1,"type":"job.started","job_id":"j1","ts":0}',
                '{"seq":2,"type":"job.finished","job_id":"j1","ts":1}',
            ),
            headers={"Content-Type": "text/event-stream"},
        )
    )
    rt = HttpxJobRuntime(HOST)
    try:
        events = [ev async for ev in rt.watch("j1")]
        skipped = [ev async for ev in rt.watch("j1", after_seq=1)]
    finally:
        await rt.aclose()
    assert route.call_count == 2
    assert [e.seq for e in events] == [1, 2]
    assert events[0].type == "job.started"
    assert [e.seq for e in skipped] == [2]
    assert route.calls[0].request.url.params[FROM_SEQ_PARAM] == "0"


@pytest.mark.asyncio
@respx.mock
async def test_watch_404_is_130004() -> None:
    respx.get(events_url(HOST, "missing")).mock(return_value=httpx.Response(404))
    rt = HttpxJobRuntime(HOST)
    try:
        with pytest.raises(JobError) as ei:
            _ = [ev async for ev in rt.watch("missing")]
    finally:
        await rt.aclose()
    assert ei.value.code is ErrorCode.JOBS_NOT_FOUND


@pytest.mark.asyncio
@respx.mock
async def test_watch_503_is_130001() -> None:
    respx.get(events_url(HOST, "j1")).mock(return_value=httpx.Response(503))
    rt = HttpxJobRuntime(HOST)
    try:
        with pytest.raises(JobError) as ei:
            _ = [ev async for ev in rt.watch("j1")]
    finally:
        await rt.aclose()
    assert ei.value.code is ErrorCode.JOBS_UNAVAILABLE


@pytest.mark.asyncio
@respx.mock
async def test_malformed_sse_is_130005() -> None:
    respx.get(events_url(HOST, "j1")).mock(
        return_value=httpx.Response(200, text="data: not-json\n\n")
    )
    rt = HttpxJobRuntime(HOST)
    try:
        with pytest.raises(JobError) as ei:
            _ = [ev async for ev in rt.watch("j1")]
    finally:
        await rt.aclose()
    assert ei.value.code is ErrorCode.JOBS_WATCH_FAILED


@pytest.mark.asyncio
async def test_run_get_cancel_unavailable_on_current_sidecar() -> None:
    rt = HttpxJobRuntime(HOST)
    try:
        with pytest.raises(JobError) as ei:
            await rt.run({"goal": "x", "units": []})
        assert ei.value.code is ErrorCode.JOBS_UNAVAILABLE
        with pytest.raises(JobError) as ei:
            await rt.get("j1")
        assert ei.value.code is ErrorCode.JOBS_UNAVAILABLE
        with pytest.raises(JobError) as ei:
            await rt.cancel("j1")
        assert ei.value.code is ErrorCode.JOBS_UNAVAILABLE
    finally:
        await rt.aclose()


def test_from_config_wires_http_runtime_when_host_set(tmp_path) -> None:
    import json
    from pathlib import Path

    from zeus_client.adapters.jobs_http.client import HttpxJobRuntime

    p = Path(tmp_path) / "cfg.json"
    p.write_text(json.dumps({"jobs": {"host_url": HOST}}), encoding="utf-8")
    rt = ZeusRuntime.from_config(p, profile="development", env={})
    assert isinstance(rt.services.jobs, HttpxJobRuntime)
    assert rt.services.jobs.host_url == HOST
