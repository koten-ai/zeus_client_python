"""Parse Helios-style SSE JobEvent frames."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import JobEvent


def _ts_ms(raw: Any) -> int:
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw:
        try:
            text = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp() * 1000)
        except ValueError:
            return 0
    return 0


def job_event_from_wire(payload: MappingLike) -> JobEvent:
    data = dict(payload)
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    return JobEvent(
        seq=int(data.get("seq") or 0),
        type=str(data.get("type") or ""),
        job_id=str(data.get("job_id") or ""),
        ts_ms=_ts_ms(data.get("ts") if "ts" in data else data.get("ts_ms")),
        unit_id=data.get("unit_id") or None,
        wave=data.get("wave"),
        plan_epoch=data.get("plan_epoch"),
        payload=dict(extra) if extra else {k: v for k, v in data.items() if k not in _WIRE_FIXED},
    )


_WIRE_FIXED = {
    "schema",
    "seq",
    "job_id",
    "ts",
    "ts_ms",
    "type",
    "plan_epoch",
    "unit_id",
    "wave",
    "extra",
}

MappingLike = dict[str, Any]


def iter_sse_events(body: str) -> Iterable[JobEvent]:
    """Yield JobEvents from an SSE body. Malformed data lines raise 130005."""
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            current.append(line[5:].lstrip())
        elif line.strip() == "":
            if current:
                raw = "\n".join(current)
                current = []
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise JobError(
                        code=ErrorCode.JOBS_WATCH_FAILED,
                        component="adapters.jobs_http.sse",
                    ) from exc
                if not isinstance(parsed, dict):
                    raise JobError(
                        code=ErrorCode.JOBS_WATCH_FAILED,
                        component="adapters.jobs_http.sse",
                    )
                yield job_event_from_wire(parsed)
    if current:
        raw = "\n".join(current)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JobError(
                code=ErrorCode.JOBS_WATCH_FAILED,
                component="adapters.jobs_http.sse",
            ) from exc
        if not isinstance(parsed, dict):
            raise JobError(code=ErrorCode.JOBS_WATCH_FAILED, component="adapters.jobs_http.sse")
        yield job_event_from_wire(parsed)
