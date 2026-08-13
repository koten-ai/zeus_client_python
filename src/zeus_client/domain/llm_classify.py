"""Family LLM HTTP/JSON → error class + ErrorCode (ZCM-008 / FAMILY_LLM_ERRORS).

Pure domain — no httpx. Adapters call ``classify_llm_failure`` then raise ``LlmError``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from zeus_client.domain.errors import ErrorCode, default_retryable

__all__ = [
    "LlmErrorClass",
    "LlmClassification",
    "RetryBudget",
    "classify_llm_failure",
    "error_code_for_class",
]


class LlmErrorClass(str, Enum):
    """Closed ENUM — family ``llm.error_class``."""

    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH = "auth"
    CONTEXT_LENGTH = "context_length"
    CONTENT_FILTER = "content_filter"
    PROVIDER_OVERLOAD = "provider_overload"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"
    TOOL_SCHEMA = "tool_schema"
    UNKNOWN = "unknown"


_CLASS_TO_CODE: dict[LlmErrorClass, ErrorCode] = {
    LlmErrorClass.RATE_LIMIT: ErrorCode.LLM_RATE_LIMIT,
    LlmErrorClass.QUOTA_EXHAUSTED: ErrorCode.LLM_QUOTA_EXHAUSTED,
    LlmErrorClass.AUTH: ErrorCode.LLM_AUTH,
    LlmErrorClass.CONTEXT_LENGTH: ErrorCode.LLM_CONTEXT_LENGTH,
    LlmErrorClass.CONTENT_FILTER: ErrorCode.LLM_CONTENT_FILTER,
    LlmErrorClass.PROVIDER_OVERLOAD: ErrorCode.LLM_PROVIDER_OVERLOAD,
    LlmErrorClass.PROVIDER_UNAVAILABLE: ErrorCode.LLM_PROVIDER_UNAVAILABLE,
    LlmErrorClass.TIMEOUT: ErrorCode.AGENT_LLM_TIMEOUT,
    LlmErrorClass.INVALID_REQUEST: ErrorCode.LLM_INVALID_REQUEST,
    LlmErrorClass.TOOL_SCHEMA: ErrorCode.LLM_TOOL_SCHEMA,
    LlmErrorClass.UNKNOWN: ErrorCode.AGENT_LLM_REQUEST_FAILED,
}


def error_code_for_class(cls: LlmErrorClass) -> ErrorCode:
    return _CLASS_TO_CODE.get(cls, ErrorCode.AGENT_LLM_REQUEST_FAILED)


@dataclass(frozen=True, slots=True)
class LlmClassification:
    """Result of classifying one LLM failure."""

    error_class: LlmErrorClass
    code: ErrorCode
    retryable: bool
    http_status: int | None = None
    provider_code: str | None = None
    provider_type: str | None = None
    message_preview: str = ""

    def to_meta(self) -> dict[str, Any]:
        """Safe attrs for journal / result meta (no secrets)."""
        return {
            "llm.error_class": self.error_class.value,
            "error.code": self.code.value,
            "error.retryable": self.retryable,
            "http.status_code": self.http_status,
            "llm.provider_code": self.provider_code,
            "llm.provider_type": self.provider_type,
        }


@dataclass
class RetryBudget:
    """Per-turn retry budget — only retryable classes may consume attempts.

    ``max_attempts`` counts *extra* tries after the first failure (total HTTP
    posts ≈ 1 + max_attempts when every failure is retryable). Matches
    ``RetryPolicy.max_attempts`` semantics used by adapters.
    """

    max_attempts: int = 3
    max_extra_ms: int = 30_000
    attempts_used: int = 0
    ms_used: int = 0

    def allow(self, *, retryable: bool, delay_ms: int = 0) -> bool:
        if not retryable:
            return False
        if self.attempts_used >= self.max_attempts:
            return False
        if delay_ms < 0:
            delay_ms = 0
        if self.ms_used + delay_ms > self.max_extra_ms:
            return False
        return True

    def consume(self, delay_ms: int = 0) -> None:
        self.attempts_used += 1
        if delay_ms > 0:
            self.ms_used += delay_ms


def _as_mapping(body: Any) -> Mapping[str, Any]:
    if isinstance(body, Mapping):
        return body
    return {}


def _extract_error_fields(body: Any) -> tuple[str | None, str | None, str]:
    """Return (provider_code, provider_type, message) from OpenAI-shaped bodies."""
    if isinstance(body, str):
        return None, None, body[:500]
    m = _as_mapping(body)
    err = m.get("error")
    if isinstance(err, str):
        return None, None, err[:500]
    if not isinstance(err, Mapping):
        # Some providers put code/message at top level
        code = m.get("code")
        typ = m.get("type")
        msg = m.get("message") or m.get("error_message") or ""
        if code or typ or msg:
            return (
                str(code) if code is not None else None,
                str(typ) if typ is not None else None,
                str(msg)[:500],
            )
        return None, None, str(body)[:500] if body is not None else ""
    code = err.get("code")
    typ = err.get("type")
    msg = err.get("message") or ""
    return (
        str(code) if code is not None else None,
        str(typ) if typ is not None else None,
        str(msg)[:500],
    )


_QUOTA_RE = re.compile(
    r"insufficient[_\s-]?quota|quota[_\s-]?exceeded|billing|credit|spend.?limit|"
    r"payment|out of credits|exceeded your current quota",
    re.I,
)
_RATE_RE = re.compile(
    r"rate[_\s-]?limit|too many requests|tokens per minute|requests per minute|rpm|tpm",
    re.I,
)
_CONTEXT_RE = re.compile(
    r"context[_\s-]?length|maximum context|max[_\s-]?tokens|token.?limit|"
    r"too many tokens|prompt is too long|context window|max_model_len|"
    r"input is too long",
    re.I,
)
_FILTER_RE = re.compile(
    r"content[_\s-]?filter|content[_\s-]?policy|safety|moderation|blocked by",
    re.I,
)
_TOOL_RE = re.compile(
    r"tool[_\s-]?choice|tools? were|function[_\s-]?call|tool[_\s-]?schema|"
    r"invalid tools|functions?",
    re.I,
)
_OVERLOAD_RE = re.compile(r"overload|capacity|overloaded|try again later", re.I)
_BILLING_AUTH_RE = re.compile(r"billing|payment|credit|subscription", re.I)


def _blob(code: str | None, typ: str | None, msg: str) -> str:
    return " ".join(x for x in (code or "", typ or "", msg or "") if x)


def classify_llm_failure(
    *,
    status: int | None = None,
    body: Any = None,
    transport_error: bool = False,
    timeout: bool = False,
) -> LlmClassification:
    """Map HTTP status + provider JSON to family class / code / retryable.

    Algorithm (FAMILY_LLM_ERRORS §2):
    1. timeout → timeout
    2. transport (no response) → provider_unavailable
    3. 401/403 (not billing) → auth
    4. 429 → quota if quota/billing markers else rate_limit
    5. 529 → overload
    6. 5xx → unavailable (or overload if capacity message)
    7. 400 context → context_length
    8. 400/422 filter → content_filter
    9. 400 tool → tool_schema else invalid_request
    10. else unknown
    """
    code_s, typ_s, msg = _extract_error_fields(body)
    text = _blob(code_s, typ_s, msg)

    def _fin(cls: LlmErrorClass) -> LlmClassification:
        ec = error_code_for_class(cls)
        return LlmClassification(
            error_class=cls,
            code=ec,
            retryable=default_retryable(ec),
            http_status=status,
            provider_code=code_s,
            provider_type=typ_s,
            message_preview=msg[:240],
        )

    if timeout:
        return _fin(LlmErrorClass.TIMEOUT)

    if transport_error or status is None:
        return _fin(LlmErrorClass.PROVIDER_UNAVAILABLE)

    st = int(status)

    # 402 Payment Required → quota
    if st == 402:
        return _fin(LlmErrorClass.QUOTA_EXHAUSTED)

    if st in (401, 403):
        if _BILLING_AUTH_RE.search(text) or _QUOTA_RE.search(text):
            return _fin(LlmErrorClass.QUOTA_EXHAUSTED)
        return _fin(LlmErrorClass.AUTH)

    if st == 429:
        # Critical: OpenAI uses 429 for both rate and insufficient_quota
        joined = text.lower()
        if (
            (code_s and "insufficient_quota" in code_s.lower())
            or (typ_s and "insufficient_quota" in typ_s.lower())
            or _QUOTA_RE.search(joined)
        ):
            return _fin(LlmErrorClass.QUOTA_EXHAUSTED)
        return _fin(LlmErrorClass.RATE_LIMIT)

    if st == 529:
        return _fin(LlmErrorClass.PROVIDER_OVERLOAD)

    if st in (500, 502, 503, 504):
        if st == 503 and _OVERLOAD_RE.search(text):
            return _fin(LlmErrorClass.PROVIDER_OVERLOAD)
        if _OVERLOAD_RE.search(text) and "capacity" in text.lower():
            return _fin(LlmErrorClass.PROVIDER_OVERLOAD)
        return _fin(LlmErrorClass.PROVIDER_UNAVAILABLE)

    if st in (400, 422):
        if _CONTEXT_RE.search(text):
            return _fin(LlmErrorClass.CONTEXT_LENGTH)
        if _FILTER_RE.search(text):
            return _fin(LlmErrorClass.CONTENT_FILTER)
        # tool_schema before generic invalid — messages often mention tools
        if code_s and "tool" in code_s.lower():
            return _fin(LlmErrorClass.TOOL_SCHEMA)
        if _TOOL_RE.search(text) and (
            "schema" in text.lower()
            or "tool_choice" in text.lower()
            or "invalid" in text.lower()
            or "function" in text.lower()
        ):
            return _fin(LlmErrorClass.TOOL_SCHEMA)
        return _fin(LlmErrorClass.INVALID_REQUEST)

    # Prefer rate markers even on odd statuses
    if _RATE_RE.search(text) and st >= 400:
        return _fin(LlmErrorClass.RATE_LIMIT)

    return _fin(LlmErrorClass.UNKNOWN)
