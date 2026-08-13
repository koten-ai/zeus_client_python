"""Contract tests for OpenAI-compatible LLM adapter (ZCP-16)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zeus_client.adapters.llm_openai_compatible import (
    OpenAICompatibleLlmClient,
    build_chat_payload,
    cache_hints,
)
from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config.models import LlmProviderConfig, RetryPolicy
from zeus_client.domain.errors import ErrorCode, LlmError
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.domain.journal.events import EVENT_LLM_ROUND
from zeus_client.domain.llm_classify import RetryBudget
from zeus_client.ports import LlmRequest


BASE = "https://api.x.ai/v1"
KEY = "sk-test-secret-key"


def _client(**kw):
    cfg = LlmProviderConfig(
        provider=kw.pop("provider", "xai"),
        base_url=BASE,
        model="grok-test",
        api_key_env="XAI_API_KEY",
        timeout_s=5.0,
    )
    secrets = EnvSecretStore(environ={"XAI_API_KEY": KEY})
    return OpenAICompatibleLlmClient(
        config=cfg,
        secrets=secrets,
        retry=kw.pop("retry", RetryPolicy(max_attempts=0, base_delay_ms=1, jitter=False)),
        budget=kw.pop("budget", RetryBudget(max_attempts=0)),
        journal=kw.pop("journal", None),
        turn_id=kw.pop("turn_id", "turn_t"),
        sleep=kw.pop("sleep", None),
        **kw,
    )


def test_cache_hints_branches() -> None:
    assert cache_hints("grok", BASE, "") == ({}, {})
    h, b = cache_hints("xai", BASE, "conv-1")
    assert h == {"x-grok-conv-id": "conv-1"}
    assert b == {}
    h2, b2 = cache_hints("openai", "https://api.openai.com/v1", "conv-2")
    assert h2 == {} and b2 == {"prompt_cache_key": "conv-2"}


def test_build_payload_tools_and_no_tools() -> None:
    base = build_chat_payload(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=(),
        temperature=0.0,
    )
    assert "tools" not in base
    assert "tool_choice" not in base

    with_tools = build_chat_payload(
        model="m",
        messages=[],
        tools=({"type": "function", "function": {"name": "find"}},),
        temperature=None,
    )
    assert with_tools["tool_choice"] == "auto"
    assert len(with_tools["tools"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_complete_happy_path_and_no_key_in_journal() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "hello",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "find", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )
    )
    journal = InMemoryJournal()
    client = _client(journal=journal)
    try:
        resp = await client.complete(
            LlmRequest(
                messages=({"role": "user", "content": "hi"},),
                tools=({"type": "function", "function": {"name": "find"}},),
                conv_id="chat-abc",
            )
        )
    finally:
        await client.aclose()

    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert req.headers.get("x-grok-conv-id") == "chat-abc"
    assert resp.content == "hello"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["function"]["name"] == "find"
    assert resp.usage.get("prompt_tokens") == 10

    events = [e for e in journal.events() if e.type == EVENT_LLM_ROUND]
    assert len(events) == 1
    blob = json.dumps(events[0].data)
    assert KEY not in blob
    assert "Authorization" not in blob or "Bearer" not in blob
    assert events[0].data.get("ok") is True


@pytest.mark.asyncio
@respx.mock
async def test_complete_429_rate_retries_then_ok() -> None:
    calls = {"n": 0}

    def _side(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"error": {"code": "rate_limit_exceeded", "message": "slow down"}},
                headers={"Retry-After": "0"},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )

    respx.post(f"{BASE}/chat/completions").mock(side_effect=_side)
    sleeps: list[float] = []

    async def _sleep(s: float) -> None:
        sleeps.append(s)

    client = _client(
        retry=RetryPolicy(max_attempts=2, base_delay_ms=10, jitter=False),
        budget=RetryBudget(max_attempts=2, max_extra_ms=60_000),
        sleep=_sleep,
    )
    try:
        resp = await client.complete(
            LlmRequest(messages=({"role": "user", "content": "x"},))
        )
    finally:
        await client.aclose()

    assert resp.content == "ok"
    assert calls["n"] == 2
    assert sleeps  # at least one backoff


@pytest.mark.asyncio
@respx.mock
async def test_complete_429_quota_never_retries() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            429,
            json={
                "error": {
                    "code": "insufficient_quota",
                    "type": "insufficient_quota",
                    "message": "You exceeded your current quota",
                }
            },
        )
    )
    sleeps: list[float] = []

    async def _sleep(s: float) -> None:
        sleeps.append(s)

    client = _client(
        retry=RetryPolicy(max_attempts=5, base_delay_ms=1, jitter=False),
        budget=RetryBudget(max_attempts=5),
        sleep=_sleep,
    )
    try:
        with pytest.raises(LlmError) as ei:
            await client.complete(LlmRequest(messages=({"role": "user", "content": "x"},)))
    finally:
        await client.aclose()

    assert ei.value.code is ErrorCode.LLM_QUOTA_EXHAUSTED
    assert ei.value.retryable is False
    assert route.call_count == 1
    assert sleeps == []


@pytest.mark.asyncio
@respx.mock
async def test_complete_context_length_no_retry() -> None:
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "context_length_exceeded",
                    "message": "maximum context length exceeded",
                }
            },
        )
    )
    client = _client(
        retry=RetryPolicy(max_attempts=3, base_delay_ms=1, jitter=False),
        budget=RetryBudget(max_attempts=3),
    )
    try:
        with pytest.raises(LlmError) as ei:
            await client.complete(LlmRequest(messages=({"role": "user", "content": "x"},)))
    finally:
        await client.aclose()

    assert ei.value.code is ErrorCode.LLM_CONTEXT_LENGTH
    assert ei.value.retryable is False


@pytest.mark.asyncio
async def test_missing_api_key() -> None:
    cfg = LlmProviderConfig(base_url=BASE, model="m", api_key_env="MISSING_KEY")
    client = OpenAICompatibleLlmClient(
        config=cfg,
        secrets=EnvSecretStore(environ={}),
        budget=RetryBudget(max_attempts=0),
    )
    try:
        with pytest.raises(LlmError) as ei:
            await client.complete(LlmRequest(messages=({"role": "user", "content": "x"},)))
    finally:
        await client.aclose()
    assert ei.value.code is ErrorCode.LLM_API_KEY_MISSING
