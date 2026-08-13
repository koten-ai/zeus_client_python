"""Data-plane verb use-case — typed VerbResult, no public pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from zeus_client.adapters.zeus_http.verbs import EXPOSED_V2_VERB_SET, EXPOSED_V2_VERBS
from zeus_client.config.models import DataTarget
from zeus_client.domain.errors import ErrorCode, ZeusToolError
from zeus_client.ports import VerbRequest
from zeus_client.ports.zeus import ZeusPort

__all__ = ["VerbResult", "run_data_verb", "EXPOSED_V2_VERBS"]


@dataclass(frozen=True, slots=True)
class VerbResult:
    """Public typed outcome of one direct V2 verb (no tuple returns)."""

    verb: str
    ok: bool
    status_code: int
    req_id: str | None
    body: Mapping[str, Any]
    error: str | None = None
    url_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "ok": self.ok,
            "status_code": self.status_code,
            "req_id": self.req_id,
            "body": dict(self.body),
            "error": self.error,
            "url_hint": self.url_hint,
        }


async def run_data_verb(
    zeus: ZeusPort,
    verb: str,
    body: Mapping[str, Any] | None = None,
    *,
    target: DataTarget,
    mode_header: str = "analytics",
    headers: Mapping[str, str] | None = None,
) -> VerbResult:
    """Execute one allow-listed V2 verb via ZeusPort. Rejects ``pipeline``."""
    name = (verb or "").strip()
    if name == "pipeline":
        raise ZeusToolError(
            code=ErrorCode.ZEUS_PIPELINE_NOT_ON_DIRECT,
            component="application.data_verb",
            public_message="zeus pipeline not on direct surface",
        )
    if name not in EXPOSED_V2_VERB_SET:
        raise ZeusToolError(
            code=ErrorCode.ZEUS_VERB_NOT_ALLOWED,
            component="application.data_verb",
            public_message="zeus verb not allow-listed",
            details={"verb": name, "allowed": list(EXPOSED_V2_VERBS)},
        )
    hop = await zeus.call_verb(
        VerbRequest(
            verb=name,
            body=dict(body or {}),
            target=target,
            mode_header=mode_header,
            headers=dict(headers or {}),
        )
    )
    return VerbResult(
        verb=name,
        ok=hop.ok,
        status_code=hop.status_code,
        req_id=hop.req_id,
        body=hop.body,
        error=hop.error,
    )
