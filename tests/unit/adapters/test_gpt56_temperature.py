"""ZCP-129 — gpt-5.6 rejects temperature 0 and max_tokens."""

from __future__ import annotations

import pytest

from zeus_client.adapters.llm_openai_compatible import (
    build_chat_payload,
    omits_temperature,
)

_GPT56 = (
    "gpt-5.6",
    "GPT-5.6",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
    "openai/gpt-5.6",
    "openai/gpt-5.6-sol",
    "gpt-5.6:2026-08-01",
    "  gpt-5.6  ",
)

_OTHER = (
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-5",
    "gpt-5.60",
    "gpt-5.6extra",
    "grok-4.5-latest",
    "claude-opus-4-6",
)


@pytest.mark.parametrize("model", _GPT56)
def test_gpt56_omits_temperature_even_when_zero(model: str) -> None:
    assert omits_temperature(model) is True
    payload = build_chat_payload(
        model=model,
        messages=[{"role": "user", "content": "ipa"}],
        temperature=0.0,
    )
    assert "temperature" not in payload
    assert payload["model"] == model


def test_explicit_temperature_one_still_omitted() -> None:
    payload = build_chat_payload(
        model="gpt-5.6",
        messages=[],
        temperature=1.0,
    )
    assert "temperature" not in payload


def test_body_extra_cannot_restore_temperature() -> None:
    payload = build_chat_payload(
        model="gpt-5.6-sol",
        messages=[],
        temperature=0.0,
        body_extra={"temperature": 0, "prompt_cache_key": "chat-1"},
    )
    assert "temperature" not in payload
    assert payload["prompt_cache_key"] == "chat-1"


def test_max_tokens_becomes_max_completion_tokens() -> None:
    payload = build_chat_payload(
        model="gpt-5.6",
        messages=[],
        temperature=0.0,
        max_tokens=16,
    )
    assert payload["max_completion_tokens"] == 16
    assert "max_tokens" not in payload
    assert "temperature" not in payload


def test_body_extra_max_tokens_is_renamed() -> None:
    payload = build_chat_payload(
        model="openai/gpt-5.6",
        messages=[],
        body_extra={"max_tokens": 8},
    )
    assert payload["max_completion_tokens"] == 8
    assert "max_tokens" not in payload


def test_explicit_max_completion_tokens_wins() -> None:
    payload = build_chat_payload(
        model="gpt-5.6",
        messages=[],
        max_tokens=4,
        body_extra={"max_completion_tokens": 9, "max_tokens": 3},
    )
    assert payload["max_completion_tokens"] == 9
    assert "max_tokens" not in payload


@pytest.mark.parametrize("model", _OTHER)
def test_other_models_still_send_temperature_and_max_tokens(model: str) -> None:
    assert omits_temperature(model) is False
    payload = build_chat_payload(
        model=model,
        messages=[],
        temperature=0.0,
        max_tokens=12,
    )
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 12
    assert "max_completion_tokens" not in payload


def test_unset_model_does_not_omit() -> None:
    assert omits_temperature(None) is False
    assert omits_temperature("  ") is False


def test_unset_temperature_stays_off_the_body() -> None:
    payload = build_chat_payload(model="gpt-4o", messages=[], temperature=None)
    assert "temperature" not in payload
