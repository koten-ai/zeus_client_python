"""Claude 4.7+ sampling omit and public LLM rejection text (ZCP-128)."""

from __future__ import annotations

import pytest

from zeus_client.adapters.llm_openai_compatible import (
    build_chat_payload,
    omits_sampling_params,
    public_message_for_llm_failure,
)
from zeus_client.domain.llm_classify import classify_llm_failure

_OMIT = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-opus-5-5",
    "Claude-Opus-5-5",
    "claude-sonnet-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-fable-5-1",
    "claude-opus-4-7-20260416",
    "anthropic.claude-opus-4-7",
    "anthropic/claude-opus-4-7",
    "us.anthropic.claude-opus-5-5",
    "anthropic.claude-opus-4-7:0",
    "claude-mythos-preview",
    "claude-opus-4.7",
    "Claude-Opus-4.7",
    "anthropic/claude-opus-4.7",
    "anthropic/claude-opus-4.7-fast",
    "anthropic/claude-opus-5.5",
    "claude-opus-5.5",
    "claude-opus-4-7-fast",
)

_KEEP = (
    "",
    "grok-4",
    "gpt-4o",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-4-6-v1",
    "anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-opus-4-6-v1",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-3-5-sonnet-20241022",
    "claude-3-7-sonnet-20250219",
    "claude-3-opus-20240229",
    "claude-opus-4",
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
    "anthropic.claude-opus-4-20250514-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-opus-4-1-20250805",
    "claude-opus-4.6",
    "claude-sonnet-4-5-20250929-v1:0",
)


@pytest.mark.parametrize("model", _OMIT)
def test_claude_4_7_and_later_omit_sampling(model: str) -> None:
    assert omits_sampling_params(model) is True


@pytest.mark.parametrize("model", _KEEP)
def test_older_and_other_models_keep_sampling(model: str) -> None:
    assert omits_sampling_params(model) is False


def test_none_model_keeps_sampling() -> None:
    assert omits_sampling_params(None) is False


def test_opus_5_5_strips_sampling_even_from_body_extra() -> None:
    payload = build_chat_payload(
        model="claude-opus-5-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0,
        body_extra={
            "temperature": 0.2,
            "top_p": 0.99,
            "top_k": 5,
            "prompt_cache_key": "conv-1",
        },
    )
    assert payload["model"] == "claude-opus-5-5"
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "top_k" not in payload
    assert payload["prompt_cache_key"] == "conv-1"


def test_explicit_temperature_one_still_omitted_for_opus_5_5() -> None:
    payload = build_chat_payload(
        model="claude-opus-4-7",
        messages=[],
        temperature=1.0,
        body_extra={"top_p": 1, "top_k": 0},
    )
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "top_k" not in payload


def test_grok_still_sends_temperature_and_top_p() -> None:
    payload = build_chat_payload(
        model="grok-4",
        messages=[],
        temperature=0.0,
        body_extra={"top_p": 0.9},
    )
    assert payload["temperature"] == 0.0
    assert payload["top_p"] == 0.9


def test_opus_5_5_keeps_max_tokens() -> None:
    payload = build_chat_payload(
        model="claude-opus-5-5",
        messages=[],
        temperature=0.0,
        max_tokens=12,
    )
    assert "temperature" not in payload
    assert payload["max_tokens"] == 12
    assert "max_completion_tokens" not in payload


def test_opus_5_5_still_sends_tool_choice_auto() -> None:
    payload = build_chat_payload(
        model="claude-opus-5-5",
        messages=[],
        tools=({"type": "function", "function": {"name": "find"}},),
        temperature=0.0,
    )
    assert payload["tool_choice"] == "auto"
    assert "temperature" not in payload


def test_public_message_keeps_provider_sentence_on_400() -> None:
    classified = classify_llm_failure(
        status=400,
        body={
            "error": {
                "type": "invalid_request_error",
                "message": "`temperature` is deprecated for this model.",
            }
        },
    )
    assert public_message_for_llm_failure(classified) == (
        "llm invalid request: `temperature` is deprecated for this model."
    )


def test_public_message_redacts_key_and_collapses_whitespace() -> None:
    classified = classify_llm_failure(
        status=422,
        body={"error": {"message": "bad\nkey sk-abcdefghijklmnopqrstuvwxyz"}},
    )
    text = public_message_for_llm_failure(classified)
    assert "sk-" not in text
    assert "[redacted]" in text
    assert "\n" not in text
    assert text.startswith("llm invalid request: ")


def test_public_message_caps_provider_sentence() -> None:
    classified = classify_llm_failure(
        status=400,
        body={"error": {"message": "x" * 240}},
    )
    text = public_message_for_llm_failure(classified)
    assert text.startswith("llm invalid request: ")
    assert len(text.split(": ", 1)[1]) == 200


def test_public_message_empty_400_stays_on_catalog_string() -> None:
    classified = classify_llm_failure(status=400, body={"error": {}})
    assert public_message_for_llm_failure(classified) == "llm invalid request"


def test_public_message_429_stays_on_catalog_string() -> None:
    classified = classify_llm_failure(
        status=429,
        body={"error": {"message": "slow down", "code": "rate_limit_exceeded"}},
    )
    assert public_message_for_llm_failure(classified) == "llm rate limited (throttle)"
