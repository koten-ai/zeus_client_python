"""Immutable V2 runtime configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

__all__ = [
    "AuthMode",
    "ZeusEndpointConfig",
    "DataTarget",
    "LlmProviderConfig",
    "ClientSettings",
    "RetryPolicy",
    "RedactionPolicy",
    "DebugPolicy",
    "RuntimeConfig",
]

AuthMode = Literal["none", "basic", "bearer", "session"]


def _redact_repr_value(key: str, value: Any) -> Any:
    lk = key.lower()
    if any(s in lk for s in ("password", "token", "secret", "api_key", "authorization")):
        return "***"
    return value


@dataclass(frozen=True, slots=True)
class ZeusEndpointConfig:
    url: str = "http://127.0.0.1:8080"
    auth_mode: AuthMode = "none"
    username: str | None = None
    password_env: str | None = None  # env var name only — never the secret
    token_env: str | None = None
    timeout_s: float = 30.0

    def __repr__(self) -> str:
        return (
            f"ZeusEndpointConfig(url={self.url!r}, auth_mode={self.auth_mode!r}, "
            f"username={self.username!r}, password_env={self.password_env!r}, "
            f"token_env={self.token_env!r}, timeout_s={self.timeout_s!r})"
        )


@dataclass(frozen=True, slots=True)
class DataTarget:
    bucket: str = "yelp-data"
    scope: str = "_default"
    collection: str = "_default"


@dataclass(frozen=True, slots=True)
class LlmProviderConfig:
    provider: str = "xai"
    base_url: str = "https://api.x.ai/v1"
    model: str = "grok-4-1-non-reasoning"
    api_key_env: str = "XAI_API_KEY"  # env var name only
    context_window_tokens: int = 128_000
    context_soft_limit: float = 0.8
    timeout_s: float = 120.0

    def __repr__(self) -> str:
        return (
            f"LlmProviderConfig(provider={self.provider!r}, base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key_env={self.api_key_env!r}, "
            f"context_window_tokens={self.context_window_tokens!r}, "
            f"context_soft_limit={self.context_soft_limit!r}, timeout_s={self.timeout_s!r})"
        )


@dataclass(frozen=True, slots=True)
class ClientSettings:
    """Product loop settings. Package default ai_process_result=True (Hub parity)."""

    ai_process_result: bool = True
    max_rounds: int = 8
    force_trace: bool = False
    mode: str = "analytics"
    durable_sessions: bool = True
    # Policy / Layer A control plane (ZCM-011)
    sticky_flags: Mapping[str, bool] = field(default_factory=dict)
    messages: Mapping[str, str] = field(default_factory=dict)
    soft_require_policy_action: bool = True
    allow_array_triggers: bool = True
    app_output_on_error: str = "strip"  # "strip" | "fail"
    output_request: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 200
    max_delay_ms: int = 5_000
    jitter: bool = True


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    enabled: bool = True
    preview_max_chars: int = 2048  # prod default; profiles may raise for dev


@dataclass(frozen=True, slots=True)
class DebugPolicy:
    detective_briefing: bool = True
    capture_bodies: bool = False  # prod default off; dev may enable
    transport_replay: bool = True


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Immutable config after bind (loader output)."""

    profile: str = "development"
    zeus: ZeusEndpointConfig = field(default_factory=ZeusEndpointConfig)
    target: DataTarget = field(default_factory=DataTarget)
    llm: LlmProviderConfig = field(default_factory=LlmProviderConfig)
    settings: ClientSettings = field(default_factory=ClientSettings)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    redaction: RedactionPolicy = field(default_factory=RedactionPolicy)
    debug: DebugPolicy = field(default_factory=DebugPolicy)
    chat_requests_dir: str | None = None

    def __repr__(self) -> str:
        # Never dump nested secrets; models already use env-name-only fields.
        return (
            f"RuntimeConfig(profile={self.profile!r}, zeus={self.zeus!r}, "
            f"target={self.target!r}, llm={self.llm!r}, settings={self.settings!r}, "
            f"retry={self.retry!r}, redaction={self.redaction!r}, debug={self.debug!r}, "
            f"chat_requests_dir={self.chat_requests_dir!r})"
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Export snapshot safe for logs / support packs (no secret values)."""
        return {
            "profile": self.profile,
            "zeus": {
                "url": self.zeus.url,
                "auth_mode": self.zeus.auth_mode,
                "username": self.zeus.username,
                "password_env": self.zeus.password_env,
                "token_env": self.zeus.token_env,
                "timeout_s": self.zeus.timeout_s,
            },
            "target": {
                "bucket": self.target.bucket,
                "scope": self.target.scope,
                "collection": self.target.collection,
            },
            "llm": {
                "provider": self.llm.provider,
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "api_key_env": self.llm.api_key_env,
                "context_window_tokens": self.llm.context_window_tokens,
                "context_soft_limit": self.llm.context_soft_limit,
                "timeout_s": self.llm.timeout_s,
            },
            "settings": {
                "ai_process_result": self.settings.ai_process_result,
                "max_rounds": self.settings.max_rounds,
                "force_trace": self.settings.force_trace,
                "mode": self.settings.mode,
                "durable_sessions": self.settings.durable_sessions,
                "soft_require_policy_action": self.settings.soft_require_policy_action,
                "allow_array_triggers": self.settings.allow_array_triggers,
                "app_output_on_error": self.settings.app_output_on_error,
                # sticky_flags / messages / output_request omitted from public dict
                # when empty; presence of keys only (no secret values).
                "sticky_flag_keys": sorted(str(k) for k in self.settings.sticky_flags),
                "message_keys": sorted(str(k) for k in self.settings.messages),
                "has_output_request": self.settings.output_request is not None,
            },
            "retry": {
                "max_attempts": self.retry.max_attempts,
                "base_delay_ms": self.retry.base_delay_ms,
                "max_delay_ms": self.retry.max_delay_ms,
                "jitter": self.retry.jitter,
            },
            "redaction": {
                "enabled": self.redaction.enabled,
                "preview_max_chars": self.redaction.preview_max_chars,
            },
            "debug": {
                "detective_briefing": self.debug.detective_briefing,
                "capture_bodies": self.debug.capture_bodies,
                "transport_replay": self.debug.transport_replay,
            },
            "chat_requests_dir": self.chat_requests_dir,
        }

    def with_overrides(self, **kwargs: Any) -> RuntimeConfig:
        return replace(self, **kwargs)
