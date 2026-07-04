"""Upstream LLM (OpenAI-compatible) client."""
from zeus_client.constants import UPSTREAM_TIMEOUT
from zeus_client.http_client import client

def cache_hints(provider_id, base_url, conv_id):
    """Provider-aware prompt-caching hints.

    Prompt caching is automatic on every major provider we ship (xAI,
    OpenAI, Gemini, DeepSeek): the static prefix — our ~24k-char system
    prompt + the tool catalog, which we always send first and never
    mutate — is reused across the multi-round agent loop and across
    turns of the same chat, billed at the reduced cached rate. We don't
    "turn it on"; we just feed the provider the routing key that keeps
    a conversation pinned to the same cache server so the hit rate stays
    high (xAI/OpenAI both warn the cache is best-effort otherwise).

    Returns (extra_headers, body_extra). `conv_id` is the stable chat id.
    """
    extra_headers, body_extra = {}, {}
    if not conv_id:
        return extra_headers, body_extra
    pid = (provider_id or "").lower()
    url = (base_url or "").lower()
    if pid == "grok" or "x.ai" in url:
        # xAI: stable conv id maximizes cache-hit rate (docs.x.ai).
        extra_headers["x-grok-conv-id"] = conv_id
    elif pid == "openai" or "api.openai.com" in url:
        # OpenAI: prompt_cache_key improves cache routing/bucketing.
        body_extra["prompt_cache_key"] = conv_id
    # Other OpenAI-compatible providers cache automatically on prefix
    # match with no extra signal; nothing to add.
    return extra_headers, body_extra


def cached_tokens_of(resp):
    """Best-effort read of cached prompt tokens from an OpenAI-shaped
    usage block (xAI/OpenAI report it under prompt_tokens_details)."""
    if not isinstance(resp, dict):
        return None
    usage = resp.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return details.get("cached_tokens", usage.get("cached_tokens"))


def llm_payload(model, messages, tools, body_extra=None):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    # When there are no tools we must NOT set tool_choice (OpenAI-compatible
    # providers 400 with "tool_choice was set but no tools were specified").
    # This is important when testing new standardized catalogs (e.g. the
    # chat_request_prototype) before their verbs have been wired into the
    # prompt assembly, or for text-only / future tool-less modes.
    if body_extra:
        payload.update(body_extra)
    return payload


async def llm_chat_payload(base_url, api_key, payload, extra_headers=None):
    """POST one chat-completion round to the provider. Async so the
    event loop serves other users while this (slow) call is in flight."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    r = await client().post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload, timeout=UPSTREAM_TIMEOUT,
    )
    is_json = r.headers.get("content-type", "").startswith("application/json")
    return r.status_code, (r.json() if is_json else r.text)
