"""HTTP/SSE JobRuntimePort — WatchJob only on current Go sidecar."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from zeus_client.adapters.jobs_http.paths import FROM_SEQ_PARAM, events_url
from zeus_client.adapters.jobs_http.sse import iter_sse_events
from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import JobEvent, JobHandle, JobSnapshot

__all__ = ["HttpxJobRuntime"]


class HttpxJobRuntime:
    """Pattern B client. run/get/cancel stay 130001 until sidecar grows routes."""

    def __init__(self, host_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.host_url = host_url.rstrip("/")
        self._client = client
        self._owns = client is None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def aclose(self) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def run(self, request: Mapping[str, Any]) -> JobHandle:
        _reject_secrets(request)
        raise JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="adapters.jobs_http")

    async def get(self, job_id: str) -> JobSnapshot:
        raise JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="adapters.jobs_http")

    async def cancel(self, job_id: str) -> JobSnapshot:
        raise JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="adapters.jobs_http")

    def watch(self, job_id: str, *, after_seq: int = 0) -> AsyncIterator[JobEvent]:
        return self._watch(job_id, after_seq=after_seq)

    async def _watch(self, job_id: str, *, after_seq: int = 0) -> AsyncIterator[JobEvent]:
        url = events_url(self.host_url, job_id)
        try:
            resp = await self._http().get(
                url,
                params={FROM_SEQ_PARAM: after_seq},
                headers={
                    "Accept": "text/event-stream",
                    "Last-Event-ID": str(after_seq),
                },
            )
        except httpx.HTTPError as exc:
            raise JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="adapters.jobs_http") from exc
        if resp.status_code == 404:
            raise JobError(code=ErrorCode.JOBS_NOT_FOUND, component="adapters.jobs_http")
        if resp.status_code >= 500:
            raise JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="adapters.jobs_http")
        if resp.status_code >= 400:
            raise JobError(code=ErrorCode.JOBS_WATCH_FAILED, component="adapters.jobs_http")
        for ev in iter_sse_events(resp.text):
            if ev.seq > after_seq:
                yield ev


def _reject_secrets(request: Mapping[str, Any]) -> None:
    blob = str(request)
    if "api_key" in blob and "api_key_env" not in blob:
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="adapters.jobs_http")
