"""OpenAI-compatible LLM adapter — dedicated httpx client, classified errors.

No process-global HTTP. API keys resolved via SecretStore; never journaled.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from zeus_client.adapters.llm_openai_compatible.tool_schema import repair_openai_tool_schemas
from zeus_client.config.models import LlmProviderConfig, RetryPolicy
from zeus_client.domain.errors import ErrorCode, LlmError, public_message_for
from zeus_client.domain.journal.events import EVENT_LLM_ROUND, JournalEvent
from zeus_client.domain.journal.journal import InMemoryJournal
from zeus_client.domain.llm_classify import (
    LlmClassification,
    RetryBudget,
    classify_llm_failure,
)
from zeus_client.observability.logging import get_family_logger
from zeus_client.ports import LlmRequest, LlmResponse
from zeus_client.ports.secrets import SecretStorePort

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

COMPONENT = "adapters.llm_openai_compatible"

SleepFn = Callable[[float], Awaitable[None]]


def cache_hints(
    provider_id: str | None,
    base_url: str | None,
    conv_id: str | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Provider-aware prompt-caching hints (ported from V1 llm.client)."""
    extra_headers: dict[str, str] = {}
    body_extra: dict[str, Any] = {}
    if not conv_id:
        return extra_headers, body_extra
    pid = (provider_id or "").lower()
    url = (base_url or "").lower()
    if pid in ("grok", "xai") or "x.ai" in url:
        extra_headers["x-grok-conv-id"] = conv_id
    elif pid == "openai" or "api.openai.com" in url:
        body_extra["prompt_cache_key"] = conv_id
    return extra_headers, body_extra


def cached_tokens_of(resp: Any) -> int | None:
    if not isinstance(resp, dict):
        return None
    usage = resp.get("usage") or {}
    if not isinstance(usage, Mapping):
        return None
    details = usage.get("prompt_tokens_details") or {}
    if isinstance(details, Mapping) and details.get("cached_tokens") is not None:
        return int(details["cached_tokens"])
    if usage.get("cached_tokens") is not None:
        return int(usage["cached_tokens"])
    return None


def _model_tail(model: str | None) -> str:
    """Bare model id. A provider prefix (``openai/gpt-5.6-sol``) is stripped."""
    return (model or "").strip().lower().rsplit("/", 1)[-1]


def _is_gpt56(model: str | None) -> bool:
    """gpt-5.6 family id, including snapshots and a provider prefix.

    ``gpt-5.60`` and ``gpt-5.6extra`` do not match. This is membership only.
    Temperature and tool-call effort are separate rules below.
    """
    tail = _model_tail(model)
    return tail == "gpt-5.6" or tail.startswith(("gpt-5.6-", "gpt-5.6:"))


def omits_temperature(model: str | None) -> bool:
    """gpt-5.6 accepts only the default temperature and rejects 0.

    Omitting the field lets the provider use 1. Matches ``gpt-5.6``, route
    suffixes such as ``gpt-5.6-sol``, and a provider prefix
    (``openai/gpt-5.6``). The same ids reject ``max_tokens``.

    This helper is only that always-omit rule. ``gpt-5.5`` and ``gpt-6-sol`` /
    ``gpt-6-luna`` are false here. They drop temperature only while
    ``reasoning_effort`` is not ``none``, inside ``build_chat_payload``.
    """
    return _is_gpt56(model)


# Dated snapshots use a hyphen or a colon (``gpt-5.5-2026-04-23``).
# ``gpt-5.5-pro`` does not match. GPT-6 Astra and GPT-6.1 do not match:
# they reject ``none`` or require ``/v1/responses``.
_DATE_SUFFIX = r"(?:[:\-]\d{4}-\d{2}-\d{2})?"
_DEFAULT_REASONING_ACCEPTS_NONE = re.compile(
    rf"^(?:gpt-5\.5{_DATE_SUFFIX}|gpt-6-(?:sol|luna){_DATE_SUFFIX})$"
)


def _chat_tools_need_reasoning_none(model: str | None) -> bool:
    """Chat Completions accepts function tools on these ids only at effort none.

    They default to ``medium``. The gpt-5.6 family is included by id, not by
    calling ``omits_temperature``. ``gpt-5``, the gpt-4 ids, ``gpt-5.1``,
    ``gpt-5.2``, ``gpt-5.4``, ``gpt-6-astra``, and ``gpt-6.1`` stay out.
    """
    if _is_gpt56(model):
        return True
    return _DEFAULT_REASONING_ACCEPTS_NONE.fullmatch(_model_tail(model)) is not None


# Minor is one or two digits so a snapshot date is not Claude 4.7+. Dotted
# minors and a trailing variant such as ``-fast`` count.
# ``omits_sampling_params`` strips a provider prefix with ``rfind`` first.
_CLAUDE_NEW_ID = re.compile(
    r"claude-(?:opus|sonnet|haiku|fable)-(\d+)"
    r"(?:[.-](\d{1,2}))?"
    r"(?:-\d{8})?"
    r"(?:-v\d+)?"
    r"(?::\d+)?"
    r"(?:-[a-z]+)?"
)
_CLAUDE_MYTHOS = re.compile(r"claude-mythos(?:-preview)?")
_SAMPLING_KEYS = ("temperature", "top_p", "top_k")
_SECRET_IN_PROVIDER_TEXT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_\-]{8,}|zeus_pat_[A-Za-z0-9_\-]+|bearer\s+\S+)"
)


def omits_sampling_params(model: str | None) -> bool:
    """Claude 4.7 and later reject temperature, top_p, and top_k.

    Includes Opus 5.5 (``claude-opus-5-5`` and ``claude-opus-5.5``) and
    Claude Mythos Preview. Claude 4.6 and earlier still accept temperature.
    """
    text = (model or "").strip().lower()
    idx = text.rfind("claude-")
    if idx < 0:
        return False
    tail = text[idx:]
    if _CLAUDE_MYTHOS.fullmatch(tail):
        return True
    match = _CLAUDE_NEW_ID.fullmatch(tail)
    if match is None:
        return False
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) is not None else 0
    return major > 4 or (major == 4 and minor >= 7)


def public_message_for_llm_failure(cls: LlmClassification) -> str:
    """Stable public text. HTTP 400/422 keeps a capped provider sentence.

    Other statuses stay on the catalog string. The family log line stays
    generic. Common key shapes in the sentence are redacted.
    """
    base = public_message_for(cls.code)
    if cls.http_status not in (400, 422):
        return base
    preview = " ".join((cls.message_preview or "").split())
    preview = _SECRET_IN_PROVIDER_TEXT.sub("[redacted]", preview).strip()
    if not preview:
        return base
    return f"{base}: {preview[:200]}"


def build_chat_payload(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] = (),
    temperature: float | None = 0.0,
    max_tokens: int | None = None,
    body_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [dict(m) for m in messages],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        # Deep-copied repair (ZCP-127). OpenAI rejects catalog nodes that have
        # no type. strict stays off so additionalProperties maps still send.
        payload["tools"] = repair_openai_tool_schemas(tools)
        payload["tool_choice"] = "auto"
    # When there are no tools we must NOT set tool_choice (OpenAI-compatible
    # providers 400 with "tool_choice was set but no tools were specified").
    if body_extra:
        payload.update(dict(body_extra))
    # One pass after body_extra, so a caller cannot put a rejected field back.
    # Token cap, then tool-call effort, then temperature from that final effort.
    if _is_gpt56(model):
        if "max_completion_tokens" in payload:
            payload.pop("max_tokens", None)
        elif "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
    tools_need_none = _chat_tools_need_reasoning_none(model)
    if payload.get("tools") and tools_need_none:
        payload["reasoning_effort"] = "none"
    # gpt-5.6 rejects a non-default temperature even at effort none.
    # gpt-5.5 and gpt-6-sol / gpt-6-luna reject it only while effort is not none.
    # Claude 4.7+ rejects temperature, top_p, and top_k on every turn.
    if omits_temperature(model) or (tools_need_none and payload.get("reasoning_effort") != "none"):
        payload.pop("temperature", None)
    if omits_sampling_params(model):
        for key in _SAMPLING_KEYS:
            payload.pop(key, None)
    return payload


def parse_completion_response(body: Mapping[str, Any]) -> LlmResponse:
    choices = body.get("choices") or []
    content: str | None = None
    tool_calls: list[Mapping[str, Any]] = []
    if choices and isinstance(choices[0], Mapping):
        msg = choices[0].get("message") or {}
        if isinstance(msg, Mapping):
            c = msg.get("content")
            content = c if isinstance(c, str) else (None if c is None else str(c))
            raw_tc = msg.get("tool_calls") or ()
            if isinstance(raw_tc, Sequence):
                for tc in raw_tc:
                    if isinstance(tc, Mapping):
                        tool_calls.append(dict(tc))
    usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    return LlmResponse(
        content=content,
        tool_calls=tuple(tool_calls),
        raw=dict(body),
        usage=dict(usage) if usage else {},
    )


def _host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _backoff_ms(policy: RetryPolicy, attempt: int, retry_after_s: float | None) -> int:
    if retry_after_s is not None and retry_after_s >= 0:
        base = int(retry_after_s * 1000)
    else:
        # attempt is 0-based failure index
        base = int(policy.base_delay_ms * (2**attempt))
    base = min(base, int(policy.max_delay_ms))
    if policy.jitter and base > 0:
        base = int(base * (0.5 + random.random() * 0.5))
    return max(0, base)


@dataclass
class OpenAICompatibleLlmClient:
    """``LlmPort`` over OpenAI-compatible ``POST /chat/completions``."""

    config: LlmProviderConfig
    secrets: SecretStorePort
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    budget: RetryBudget | None = None
    journal: InMemoryJournal | None = None
    turn_id: str = ""
    client: httpx.AsyncClient | None = None
    _owns_client: bool = False
    sleep: SleepFn | None = None  # injectable for tests

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.config.timeout_s)
            self._owns_client = True
        return self.client

    async def aclose(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None

    def _resolve_api_key(self) -> str:
        name = self.config.api_key_env
        val = self.secrets.get(name) if name else None
        if not val:
            raise LlmError(
                code=ErrorCode.LLM_API_KEY_MISSING,
                component=COMPONENT,
                public_message="llm api_key missing",
                details={"api_key_env": name or ""},
            )
        return val

    def _raise_classified(self, cls: LlmClassification, *, provider: str, model: str) -> None:
        details = {
            **cls.to_meta(),
            "llm.provider": provider,
            "llm.model": model,
            "llm.base_url_host": _host_of(self.config.base_url),
        }
        if cls.message_preview:
            details["llm.message_preview"] = cls.message_preview[:200]
        get_family_logger().error(
            "zeus_client.llm.request_failed",
            **{
                "llm.provider": provider,
                "llm.model": model,
                "llm.error_class": cls.error_class.value,
                "http.status_code": cls.http_status,
                "llm.retryable": cls.retryable,
                "error.code": cls.code.value,
                "error.message": "llm request failed",
                "result": "error",
            },
        )
        raise LlmError(
            code=cls.code,
            component=COMPONENT,
            retryable=cls.retryable,
            public_message=public_message_for_llm_failure(cls),
            details=details,
        )

    def _journal_round(
        self,
        *,
        ok: bool,
        model: str,
        attempt: int,
        classification: LlmClassification | None = None,
        usage: Mapping[str, Any] | None = None,
        latency_ms: int | None = None,
        tool_call_count: int = 0,
    ) -> None:
        if self.journal is None:
            return
        data: dict[str, Any] = {
            "ok": ok,
            "llm.provider": self.config.provider,
            "llm.model": model,
            "llm.base_url_host": _host_of(self.config.base_url),
            "attempt": attempt,
            "tool_call_count": tool_call_count,
        }
        if latency_ms is not None:
            data["latency_ms"] = latency_ms
        if usage:
            # usage ints only — no bodies
            safe_u = {
                k: usage[k]
                for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens")
                if k in usage
            }
            ct = cached_tokens_of({"usage": dict(usage)})
            if ct is not None:
                safe_u.setdefault("cached_tokens", ct)
            data["usage"] = safe_u
        if classification is not None:
            data.update(classification.to_meta())
        # Never put Authorization / api key / full messages here.
        self.journal.append(
            JournalEvent(
                event_id=f"llm_{int(time.time() * 1000)}_{attempt}",
                ts_ms=int(time.time() * 1000),
                type=EVENT_LLM_ROUND,
                component=COMPONENT,
                turn_id=self.turn_id or "",
                span_id=None,
                parent_span_id=None,
                data=data,
            )
        )

    async def _sleep(self, seconds: float) -> None:
        if self.sleep is not None:
            await self.sleep(seconds)
        else:
            await asyncio.sleep(seconds)

    async def complete(self, req: LlmRequest) -> LlmResponse:
        api_key = self._resolve_api_key()
        model = req.model or self.config.model
        if not model:
            raise LlmError(
                code=ErrorCode.LLM_MODEL_MISSING,
                component=COMPONENT,
                public_message="llm model missing",
            )
        base = (self.config.base_url or "").rstrip("/")
        if not base:
            raise LlmError(
                code=ErrorCode.LLM_BASE_URL_MISSING,
                component=COMPONENT,
                public_message="llm base_url missing",
            )

        conv_id = getattr(req, "conv_id", None)
        extra_headers, body_extra = cache_hints(self.config.provider, base, conv_id)
        temp = req.temperature if req.temperature is not None else 0.0
        payload = build_chat_payload(
            model=model,
            messages=req.messages,
            tools=req.tools,
            temperature=temp,
            max_tokens=req.max_tokens,
            body_extra=body_extra or None,
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **extra_headers,
        }
        url = f"{base}/chat/completions"
        client = await self._ensure_client()
        log = get_family_logger()
        log.info(
            "zeus_client.llm.request_started",
            **{
                "llm.provider": self.config.provider,
                "llm.model": model,
                "llm.base_url_host": _host_of(self.config.base_url),
            },
        )

        budget = (
            self.budget
            if self.budget is not None
            else RetryBudget(max_attempts=self.retry.max_attempts)
        )
        attempt = 0
        while True:
            t0 = time.perf_counter()
            response: httpx.Response | None = None
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException:
                cls = classify_llm_failure(timeout=True)
                self._journal_round(
                    ok=False,
                    model=model,
                    attempt=attempt,
                    classification=cls,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                delay = _backoff_ms(self.retry, attempt, None)
                if budget.allow(retryable=cls.retryable, delay_ms=delay):
                    budget.consume(delay)
                    attempt += 1
                    await self._sleep(delay / 1000.0)
                    continue
                self._raise_classified(cls, provider=self.config.provider, model=model)
            except httpx.HTTPError:
                cls = classify_llm_failure(transport_error=True)
                self._journal_round(
                    ok=False,
                    model=model,
                    attempt=attempt,
                    classification=cls,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
                delay = _backoff_ms(self.retry, attempt, None)
                if budget.allow(retryable=cls.retryable, delay_ms=delay):
                    budget.consume(delay)
                    attempt += 1
                    await self._sleep(delay / 1000.0)
                    continue
                self._raise_classified(cls, provider=self.config.provider, model=model)

            assert response is not None
            latency_ms = int((time.perf_counter() - t0) * 1000)
            is_json = (response.headers.get("content-type") or "").startswith("application/json")
            body: Any
            if is_json:
                try:
                    body = response.json()
                except Exception:
                    body = response.text
            else:
                body = response.text

            if response.status_code < 400:
                if not isinstance(body, Mapping):
                    # Non-JSON 2xx is treated as provider failure.
                    cls = classify_llm_failure(status=500, body=body)
                    self._journal_round(
                        ok=False,
                        model=model,
                        attempt=attempt,
                        classification=cls,
                        latency_ms=latency_ms,
                    )
                    self._raise_classified(cls, provider=self.config.provider, model=model)
                parsed = parse_completion_response(body)
                self._journal_round(
                    ok=True,
                    model=model,
                    attempt=attempt,
                    usage=parsed.usage,
                    latency_ms=latency_ms,
                    tool_call_count=len(parsed.tool_calls),
                )
                usage = parsed.usage or {}
                log.info(
                    "zeus_client.llm.request_finished",
                    **{
                        "llm.provider": self.config.provider,
                        "llm.model": model,
                        "duration_ms": latency_ms,
                        "result": "ok",
                        "tokens.input": usage.get("prompt_tokens"),
                        "tokens.output": usage.get("completion_tokens"),
                    },
                )
                return parsed

            cls = classify_llm_failure(status=response.status_code, body=body)
            self._journal_round(
                ok=False,
                model=model,
                attempt=attempt,
                classification=cls,
                latency_ms=latency_ms,
            )
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            delay = _backoff_ms(self.retry, attempt, retry_after)
            if budget.allow(retryable=cls.retryable, delay_ms=delay):
                budget.consume(delay)
                attempt += 1
                await self._sleep(delay / 1000.0)
                continue
            self._raise_classified(cls, provider=self.config.provider, model=model)


def _parse_retry_after(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None
