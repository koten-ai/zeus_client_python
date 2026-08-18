"""Job runtime port — Pattern B sidecar or test fake."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from zeus_client.domain.jobs import JobEvent, JobHandle, JobSnapshot

__all__ = ["JobRuntimePort"]


@runtime_checkable
class JobRuntimePort(Protocol):
    async def run(self, request: Mapping[str, Any]) -> JobHandle: ...

    def watch(self, job_id: str, *, after_seq: int = 0) -> AsyncIterator[JobEvent]: ...

    async def get(self, job_id: str) -> JobSnapshot: ...

    async def cancel(self, job_id: str) -> JobSnapshot: ...
