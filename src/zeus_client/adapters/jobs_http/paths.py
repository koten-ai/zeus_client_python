"""HTTP path constants for Pattern B job sidecar (align with Go watchjob)."""

from __future__ import annotations

JOBS_EVENTS_PATH = "/v1/jobs/{job_id}/events"
FROM_SEQ_PARAM = "from_seq"


def events_url(host_url: str, job_id: str) -> str:
    base = host_url.rstrip("/")
    return f"{base}{JOBS_EVENTS_PATH.format(job_id=job_id)}"
