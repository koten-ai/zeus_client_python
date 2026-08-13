"""Upstream LLM client helpers."""

import httpx
import pytest
import respx
from zeus_client.llm.client import (
    cache_hints,
    cached_tokens_of,
    llm_chat_payload,
    llm_payload,
)

BASE = "https://api.x.ai/v1"
KEY = "sk-test"


def test_cache_hints_branches():
    assert cache_hints("grok", BASE, "") == ({}, {})
    h, b = cache_hints("grok", BASE, "conv-1")
    assert h == {"x-grok-conv-id": "conv-1"}
    assert b == {}
    h2, b2 = cache_hints("openai", "https://api.openai.com/v1", "conv-2")
    assert h2 == {}
    assert b2 == {"prompt_cache_key": "conv-2"}
    h3, b3 = cache_hints("other", "https://example.com/v1", "conv-3")
    assert h3 == {} and b3 == {}


def test_cached_tokens_of_branches():
    assert cached_tokens_of("text") is None
    assert cached_tokens_of({}) is None
    assert cached_tokens_of({"usage": {"cached_tokens": 9}}) == 9
    assert (
        cached_tokens_of(
            {
                "usage": {"prompt_tokens_details": {"cached_tokens": 42}},
            }
        )
        == 42
    )


def test_llm_payload_with_and_without_tools():
    base = llm_payload("m", [{"role": "user", "content": "hi"}], None)
    assert "tools" not in base
    assert "tool_choice" not in base

    with_tools = llm_payload("m", [], [{"type": "function", "function": {"name": "find"}}])
    assert with_tools["tool_choice"] == "auto"
    assert len(with_tools["tools"]) == 1

    extra = llm_payload("m", [], [], body_extra={"stream": False})
    assert extra["stream"] is False


@pytest.mark.asyncio
@respx.mock
async def test_llm_chat_payload_json_and_text(http_client):
    route = respx.post(f"{BASE}/chat/completions")
    route.mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": []},
        )
    )
    status, body = await llm_chat_payload(
        BASE,
        KEY,
        {"model": "grok"},
        extra_headers={"X-Test": "1"},
    )
    assert status == 200
    assert body == {"choices": []}
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {KEY}"
    assert route.calls.last.request.headers["X-Test"] == "1"

    route.mock(return_value=httpx.Response(502, text="bad gateway"))
    status2, body2 = await llm_chat_payload(BASE, KEY, {"model": "grok"})
    assert status2 == 502
    assert body2 == "bad gateway"
