"""Unit tests for V2 ErrorCode taxonomy (ZCP-4 / Task 1.1 · ZCM-008)."""

from __future__ import annotations

import pytest

from zeus_client.domain.errors import (
    AuthError,
    CatalogError,
    ConfigError,
    ContractError,
    ErrorCode,
    InternalError,
    JobError,
    LlmError,
    PolicyError,
    SessionError,
    ValidationError,
    ZeusClientError,
    ZeusToolError,
    ZeusTransportError,
    default_retryable,
    public_message_for,
)


def test_error_code_is_six_digit_string_enum() -> None:
    assert ErrorCode.LLM_RATE_LIMIT.value == "050010"
    assert ErrorCode.LLM_QUOTA_EXHAUSTED.value == "050011"
    assert ErrorCode.LLM_CONTEXT_LENGTH.value == "050013"
    for code in ErrorCode:
        assert isinstance(code.value, str)
        assert len(code.value) == 6
        assert code.value.isdigit()


def test_family_llm_codes_050010_through_050018_present() -> None:
    expected = {
        "050010": ErrorCode.LLM_RATE_LIMIT,
        "050011": ErrorCode.LLM_QUOTA_EXHAUSTED,
        "050012": ErrorCode.LLM_AUTH,
        "050013": ErrorCode.LLM_CONTEXT_LENGTH,
        "050014": ErrorCode.LLM_CONTENT_FILTER,
        "050015": ErrorCode.LLM_PROVIDER_OVERLOAD,
        "050016": ErrorCode.LLM_PROVIDER_UNAVAILABLE,
        "050017": ErrorCode.LLM_INVALID_REQUEST,
        "050018": ErrorCode.LLM_TOOL_SCHEMA,
    }
    for digits, member in expected.items():
        assert member.value == digits
        assert ErrorCode(digits) is member


def test_llm_rate_vs_quota_retryable_flags() -> None:
    assert default_retryable(ErrorCode.LLM_RATE_LIMIT) is True
    assert default_retryable(ErrorCode.LLM_QUOTA_EXHAUSTED) is False
    assert default_retryable(ErrorCode.LLM_CONTEXT_LENGTH) is False
    assert default_retryable(ErrorCode.LLM_PROVIDER_OVERLOAD) is True
    assert default_retryable(ErrorCode.LLM_PROVIDER_UNAVAILABLE) is True
    assert default_retryable(ErrorCode.LLM_AUTH) is False


def test_zeus_client_error_fields() -> None:
    err = ZeusClientError(
        code=ErrorCode.LLM_RATE_LIMIT,
        public_message="LLM rate limited",
        component="adapters.llm",
        retryable=True,
        cause_event_id="evt_1",
        details={"http.status_code": 429},
    )
    assert err.code is ErrorCode.LLM_RATE_LIMIT
    assert err.retryable is True
    assert err.component == "adapters.llm"
    assert err.public_message == "LLM rate limited"
    assert err.cause_event_id == "evt_1"
    assert err.details["http.status_code"] == 429
    assert isinstance(err, Exception)
    assert "050010" in str(err)
    assert "LLM rate limited" in str(err)


def test_zeus_client_error_defaults_retryable_from_code() -> None:
    rate = LlmError(code=ErrorCode.LLM_RATE_LIMIT, component="llm")
    assert rate.retryable is True
    quota = LlmError(code=ErrorCode.LLM_QUOTA_EXHAUSTED, component="llm")
    assert quota.retryable is False


def test_subclass_hierarchy() -> None:
    assert issubclass(ConfigError, ZeusClientError)
    assert issubclass(AuthError, ZeusClientError)
    assert issubclass(ContractError, ZeusClientError)
    assert issubclass(CatalogError, ZeusClientError)
    assert issubclass(SessionError, ZeusClientError)
    assert issubclass(ZeusTransportError, ZeusClientError)
    assert issubclass(ZeusToolError, ZeusClientError)
    assert issubclass(LlmError, ZeusClientError)
    assert issubclass(PolicyError, ZeusClientError)
    assert issubclass(ValidationError, ZeusClientError)
    assert issubclass(InternalError, ZeusClientError)


def test_public_message_for_stable_english() -> None:
    assert "rate" in public_message_for(ErrorCode.LLM_RATE_LIMIT).lower()
    assert "quota" in public_message_for(ErrorCode.LLM_QUOTA_EXHAUSTED).lower()
    assert "context" in public_message_for(ErrorCode.LLM_CONTEXT_LENGTH).lower()


def test_raise_and_catch_by_base() -> None:
    with pytest.raises(ZeusClientError) as ei:
        raise CatalogError(
            code=ErrorCode.CATALOG_NOT_FOUND,
            component="domain.catalog",
            public_message="catalog not found",
        )
    assert ei.value.code is ErrorCode.CATALOG_NOT_FOUND
    assert ei.value.retryable is False


def test_multi_agent_error_band_130001_through_130013() -> None:
    assert ErrorCode.JOBS_UNAVAILABLE.value == "130001"
    assert ErrorCode.JOBS_INVALID_UNIT_MAP.value == "130002"
    assert ErrorCode.JOBS_BUDGET_INVALID.value == "130003"
    assert ErrorCode.JOBS_NOT_FOUND.value == "130004"
    assert ErrorCode.JOBS_WATCH_FAILED.value == "130005"
    assert ErrorCode.JOBS_UNIT_FAILED.value == "130010"
    assert ErrorCode.UNITS_CATALOG_MISSING.value == "130011"
    assert ErrorCode.UNITS_INJECT_MISSING.value == "130012"
    assert ErrorCode.UNITS_ISOLATION.value == "130013"
    err = JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="api.jobs")
    assert err.retryable is False
    assert "130001" in str(err)
    assert issubclass(JobError, ZeusClientError)
