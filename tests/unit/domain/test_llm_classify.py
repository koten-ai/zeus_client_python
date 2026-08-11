"""Table-driven LLM failure classification (ZCP-16 · FAMILY_LLM_ERRORS)."""

from __future__ import annotations

import pytest

from zeus_client_v2.domain.errors import ErrorCode
from zeus_client_v2.domain.llm_classify import (
    LlmErrorClass,
    RetryBudget,
    classify_llm_failure,
)


@pytest.mark.parametrize(
    "status,body,expected_class,expected_code,retryable",
    [
        # 429 rate vs quota — never conflate
        (
            429,
            {"error": {"code": "rate_limit_exceeded", "type": "tokens", "message": "Rate limit"}},
            LlmErrorClass.RATE_LIMIT,
            ErrorCode.LLM_RATE_LIMIT,
            True,
        ),
        (
            429,
            {
                "error": {
                    "code": "insufficient_quota",
                    "type": "insufficient_quota",
                    "message": "You exceeded your current quota",
                }
            },
            LlmErrorClass.QUOTA_EXHAUSTED,
            ErrorCode.LLM_QUOTA_EXHAUSTED,
            False,
        ),
        (
            429,
            {"error": {"message": "Too Many Requests", "type": "rate_limit_error"}},
            LlmErrorClass.RATE_LIMIT,
            ErrorCode.LLM_RATE_LIMIT,
            True,
        ),
        (
            429,
            {"error": {"message": "Billing hard limit reached", "code": "billing_not_active"}},
            LlmErrorClass.QUOTA_EXHAUSTED,
            ErrorCode.LLM_QUOTA_EXHAUSTED,
            False,
        ),
        # auth
        (
            401,
            {"error": {"message": "Incorrect API key", "type": "invalid_request_error"}},
            LlmErrorClass.AUTH,
            ErrorCode.LLM_AUTH,
            False,
        ),
        (
            403,
            {"error": {"message": "model not allowed"}},
            LlmErrorClass.AUTH,
            ErrorCode.LLM_AUTH,
            False,
        ),
        (
            403,
            {"error": {"message": "billing account suspended"}},
            LlmErrorClass.QUOTA_EXHAUSTED,
            ErrorCode.LLM_QUOTA_EXHAUSTED,
            False,
        ),
        # context
        (
            400,
            {
                "error": {
                    "message": "This model's maximum context length is 128000 tokens",
                    "code": "context_length_exceeded",
                    "type": "invalid_request_error",
                }
            },
            LlmErrorClass.CONTEXT_LENGTH,
            ErrorCode.LLM_CONTEXT_LENGTH,
            False,
        ),
        (
            400,
            {"error": {"message": "prompt is too long: 200000 tokens"}},
            LlmErrorClass.CONTEXT_LENGTH,
            ErrorCode.LLM_CONTEXT_LENGTH,
            False,
        ),
        # content filter
        (
            400,
            {"error": {"message": "Content filter blocked the request", "code": "content_filter"}},
            LlmErrorClass.CONTENT_FILTER,
            ErrorCode.LLM_CONTENT_FILTER,
            False,
        ),
        (
            422,
            {"error": {"message": "safety system blocked output"}},
            LlmErrorClass.CONTENT_FILTER,
            ErrorCode.LLM_CONTENT_FILTER,
            False,
        ),
        # tool schema
        (
            400,
            {
                "error": {
                    "message": "tool_choice was set but no tools were specified",
                    "type": "invalid_request_error",
                }
            },
            LlmErrorClass.TOOL_SCHEMA,
            ErrorCode.LLM_TOOL_SCHEMA,
            False,
        ),
        # invalid request
        (
            400,
            {"error": {"message": "Unsupported parameter: foo", "type": "invalid_request_error"}},
            LlmErrorClass.INVALID_REQUEST,
            ErrorCode.LLM_INVALID_REQUEST,
            False,
        ),
        # overload / unavailable
        (
            529,
            {"error": {"message": "Overloaded"}},
            LlmErrorClass.PROVIDER_OVERLOAD,
            ErrorCode.LLM_PROVIDER_OVERLOAD,
            True,
        ),
        (
            503,
            {"error": {"message": "capacity exhausted, overloaded"}},
            LlmErrorClass.PROVIDER_OVERLOAD,
            ErrorCode.LLM_PROVIDER_OVERLOAD,
            True,
        ),
        (
            502,
            "bad gateway",
            LlmErrorClass.PROVIDER_UNAVAILABLE,
            ErrorCode.LLM_PROVIDER_UNAVAILABLE,
            True,
        ),
        (
            500,
            {"error": {"message": "internal"}},
            LlmErrorClass.PROVIDER_UNAVAILABLE,
            ErrorCode.LLM_PROVIDER_UNAVAILABLE,
            True,
        ),
        # 402
        (
            402,
            {"error": {"message": "Payment required"}},
            LlmErrorClass.QUOTA_EXHAUSTED,
            ErrorCode.LLM_QUOTA_EXHAUSTED,
            False,
        ),
    ],
)
def test_classify_table(status, body, expected_class, expected_code, retryable) -> None:
    c = classify_llm_failure(status=status, body=body)
    assert c.error_class is expected_class
    assert c.code is expected_code
    assert c.retryable is retryable
    assert c.http_status == status
    assert c.code.value.startswith("050")


def test_classify_timeout_and_transport() -> None:
    t = classify_llm_failure(timeout=True)
    assert t.error_class is LlmErrorClass.TIMEOUT
    assert t.code is ErrorCode.AGENT_LLM_TIMEOUT
    assert t.retryable is True

    u = classify_llm_failure(transport_error=True)
    assert u.error_class is LlmErrorClass.PROVIDER_UNAVAILABLE
    assert u.code is ErrorCode.LLM_PROVIDER_UNAVAILABLE


def test_retry_budget_only_retryable() -> None:
    b = RetryBudget(max_attempts=2, max_extra_ms=10_000)
    assert b.allow(retryable=False) is False
    assert b.allow(retryable=True, delay_ms=100) is True
    b.consume(100)
    assert b.attempts_used == 1
    assert b.ms_used == 100
    b.consume(50)
    assert b.attempts_used == 2
    assert b.allow(retryable=True) is False  # attempts exhausted


def test_retry_budget_ms_cap() -> None:
    b = RetryBudget(max_attempts=10, max_extra_ms=500)
    assert b.allow(retryable=True, delay_ms=400) is True
    b.consume(400)
    assert b.allow(retryable=True, delay_ms=200) is False
