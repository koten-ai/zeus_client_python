"""OpenAI-compatible LLM adapter (xAI, OpenAI, custom OpenAI-style)."""

from __future__ import annotations

from zeus_client.adapters.llm_openai_compatible.client import (
    OpenAICompatibleLlmClient,
    build_chat_payload,
    cache_hints,
    cached_tokens_of,
    omits_sampling_params,
    omits_temperature,
    parse_completion_response,
    public_message_for_llm_failure,
)

__all__ = [
    "OpenAICompatibleLlmClient",
    "build_chat_payload",
    "cache_hints",
    "cached_tokens_of",
    "omits_sampling_params",
    "omits_temperature",
    "parse_completion_response",
    "public_message_for_llm_failure",
]
