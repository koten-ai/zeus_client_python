"""Function tools on Chat Completions need reasoning_effort none.

gpt-5.6-sol (and the same generation) defaults to medium. The endpoint
rejects that default together with function tools and asks for
/v1/responses or reasoning_effort none. gpt-5, gpt-4o, and the GPT-6
ids that cannot disable reasoning stay unchanged.
"""

from __future__ import annotations

import pytest

from zeus_client.adapters.llm_openai_compatible import build_chat_payload

_TOOLS = ({"type": "function", "function": {"name": "find"}},)

# Defaults to medium, accepts none, and Chat Completions allows tools only
# at none. Dated snapshots and a provider prefix count.
_NEEDS_NONE = (
    "gpt-5.6",
    "GPT-5.6-Sol",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.6-cyber",
    "openai/gpt-5.6-sol",
    "gpt-5.6:2026-08-01",
    "gpt-5.6-sol-2026-08-01",
    "gpt-5.6-terra:2026-08-01",
    "  gpt-5.6-sol  ",
    "gpt-5.5",
    "gpt-5.5-2026-04-23",
    "openai/gpt-5.5",
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-6-sol-2026-04-20",
    "openai/gpt-6-luna",
    "GPT-6-Luna",
)

# Already works on Chat Completions with tools, or rejects reasoning_effort
# none. Sending none would 400 or change a request that already succeeds.
_LEAVES_ALONE = (
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "gpt-5.4-2026-03-05",
    "gpt-5.5-pro",
    "gpt-5.60",
    "gpt-5.6extra",
    "gpt-6",
    "gpt-6-astra",
    "gpt-6.1-sol",
    "gpt-6.1-terra",
    "gpt-oss-120b",
    "grok-4.5-latest",
    "claude-opus-4-6",
)


@pytest.mark.parametrize("model", _NEEDS_NONE)
def test_tool_turns_send_reasoning_effort_none(model: str) -> None:
    payload = build_chat_payload(
        model=model,
        messages=[{"role": "user", "content": "ipa"}],
        tools=_TOOLS,
        temperature=0.0,
    )
    assert payload["reasoning_effort"] == "none"
    assert payload["tools"]
    assert payload["tool_choice"] == "auto"


@pytest.mark.parametrize("model", _NEEDS_NONE)
def test_turns_without_tools_do_not_send_reasoning_effort(model: str) -> None:
    payload = build_chat_payload(
        model=model,
        messages=[{"role": "user", "content": "ipa"}],
        temperature=0.0,
    )
    assert "reasoning_effort" not in payload
    assert "tools" not in payload
    assert "temperature" not in payload


@pytest.mark.parametrize("model", _LEAVES_ALONE)
def test_other_models_do_not_get_reasoning_effort(model: str) -> None:
    payload = build_chat_payload(
        model=model,
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
    )
    assert "reasoning_effort" not in payload
    assert payload["temperature"] == 0.0


def test_gpt56_tool_turn_still_omits_temperature_and_renames_max_tokens() -> None:
    payload = build_chat_payload(
        model="gpt-5.6-sol",
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
        max_tokens=16,
        body_extra={"reasoning_effort": "medium", "temperature": 0},
    )
    assert payload["reasoning_effort"] == "none"
    assert "temperature" not in payload
    assert payload["max_completion_tokens"] == 16
    assert "max_tokens" not in payload


def test_gpt55_tool_turn_keeps_temperature_because_effort_is_none() -> None:
    payload = build_chat_payload(
        model="gpt-5.5",
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
        max_tokens=12,
    )
    assert payload["reasoning_effort"] == "none"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 12
    assert "max_completion_tokens" not in payload


def test_gpt55_without_tools_omits_temperature_while_reasoning_stays_on() -> None:
    payload = build_chat_payload(
        model="openai/gpt-5.5",
        messages=[],
        temperature=0.0,
        max_tokens=12,
        body_extra={"temperature": 0.2},
    )
    assert "reasoning_effort" not in payload
    assert "temperature" not in payload
    assert payload["max_tokens"] == 12


def test_explicit_none_on_a_plain_gpt55_turn_keeps_temperature() -> None:
    payload = build_chat_payload(
        model="gpt-5.5",
        messages=[],
        temperature=0.0,
        body_extra={"reasoning_effort": "none"},
    )
    assert payload["reasoning_effort"] == "none"
    assert payload["temperature"] == 0.0


def test_gpt6_luna_tool_turn_sends_none_and_keeps_temperature() -> None:
    payload = build_chat_payload(
        model="gpt-6-luna",
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
    )
    assert payload["reasoning_effort"] == "none"
    assert payload["temperature"] == 0.0


def test_astra_tool_turn_does_not_send_none() -> None:
    payload = build_chat_payload(
        model="gpt-6-astra",
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
        body_extra={"reasoning_effort": "low"},
    )
    assert payload["reasoning_effort"] == "low"
    assert payload["temperature"] == 0.0


def test_claude_47_tool_turn_omits_temperature_and_not_reasoning_effort() -> None:
    payload = build_chat_payload(
        model="claude-opus-5-5",
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
    )
    assert "reasoning_effort" not in payload
    assert "temperature" not in payload


def test_blank_model_keeps_temperature_and_skips_reasoning_effort() -> None:
    payload = build_chat_payload(
        model="  ",
        messages=[],
        tools=_TOOLS,
        temperature=0.0,
    )
    assert "reasoning_effort" not in payload
    assert payload["temperature"] == 0.0
