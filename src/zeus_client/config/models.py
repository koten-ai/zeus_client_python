"""Immutable V2 runtime configuration models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

__all__ = [
    "AuthMode",
    "ZeusEndpointConfig",
    "DataTarget",
    "LlmProviderConfig",
    "LlmRoleConfig",
    "JobsConfig",
    "ClientSettings",
    "SemanticCacheRecallConfig",
    "SemanticCacheInjectConfig",
    "SemanticCacheWriteConfig",
    "SemanticCacheEmbedConfig",
    "SemanticCachePrivacyConfig",
    "SemanticCacheConfig",
    "RetryPolicy",
    "RedactionPolicy",
    "DebugPolicy",
    "RateLimitPolicy",
    "LoggingPolicy",
    "ClientIdentity",
    "RuntimeConfig",
]

AuthMode = Literal["none", "basic", "bearer", "session", "certificate"]


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
    tls_verify: bool = True  # production profile rejects False (SECURITY §23)
    # Per-scope basic mint: {"bucket/scope": {"username": "...", "password_env": "..."}}
    scope_credentials: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    # Deferred mTLS shape (auth_mode=certificate raises NOT_IMPLEMENTED).
    cert_file: str | None = None
    key_file: str | None = None
    key_file_env: str | None = None  # env var name only

    def __repr__(self) -> str:
        return (
            f"ZeusEndpointConfig(url={self.url!r}, auth_mode={self.auth_mode!r}, "
            f"username={self.username!r}, password_env={self.password_env!r}, "
            f"token_env={self.token_env!r}, timeout_s={self.timeout_s!r}, "
            f"tls_verify={self.tls_verify!r}, cert_file={self.cert_file!r}, "
            f"key_file_env={self.key_file_env!r})"
        )


@dataclass(frozen=True, slots=True)
class DataTarget:
    bucket: str = "yelp-data"
    scope: str = "_default"
    collection: str = "_default"


@dataclass(frozen=True, slots=True)
class LlmRoleConfig:
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    provider: str | None = None
    temperature: float | None = None

    def __repr__(self) -> str:
        return (
            f"LlmRoleConfig(model={self.model!r}, api_key_env={self.api_key_env!r}, "
            f"base_url={self.base_url!r}, provider={self.provider!r}, "
            f"temperature={self.temperature!r})"
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "provider": self.provider,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class JobsConfig:
    host_url: str | None = None
    watch_transport: Literal["sse"] = "sse"
    models: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LlmProviderConfig:
    provider: str = "xai"
    base_url: str = "https://api.x.ai/v1"
    model: str = "grok-4-1-non-reasoning"
    api_key_env: str = "XAI_API_KEY"  # env var name only
    context_window_tokens: int = 128_000
    context_soft_limit: float = 0.8
    timeout_s: float = 120.0
    roles: Mapping[str, LlmRoleConfig] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"LlmProviderConfig(provider={self.provider!r}, base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key_env={self.api_key_env!r}, "
            f"context_window_tokens={self.context_window_tokens!r}, "
            f"context_soft_limit={self.context_soft_limit!r}, timeout_s={self.timeout_s!r}, "
            f"roles={dict(self.roles)!r})"
        )


@dataclass(frozen=True, slots=True)
class ClientSettings:
    """Product loop settings. Default ai_process_result=False (CHECKLIST / API_CONFIG)."""

    ai_process_result: bool = False
    max_rounds: int = 8
    force_trace: bool = False
    mode: str = "analytics"
    durable_sessions: bool = True
    # Policy / Layer A control plane (ZCM-011)
    sticky_flags: Mapping[str, bool] = field(default_factory=dict)
    messages: Mapping[str, str] = field(default_factory=dict)
    soft_require_policy_action: bool = True
    app_output_on_error: str = "strip"  # "strip" | "fail"
    output_request: Mapping[str, Any] | None = None
    # Named rules + inject bag (CHECKLIST C)
    rules: Mapping[str, str] | None = None
    tenant_rules: Mapping[str, str] | None = None
    override_defaults: bool = False
    company_context: str | None = None
    locale: str | None = None
    language: str | None = None
    timezone: str | None = None
    channel: str | None = None
    market: str | None = None
    deployment_id: str | None = None
    ruleset_id: str | None = None
    force_return_rounds_left: int | None = 1
    ignore_user_tool_path_hints: bool = True
    tool_trail_enabled: bool = True
    tool_trail_inject: bool = True
    tool_trail_max_entries: int = 16

    def with_updates(self, **kwargs: Any) -> ClientSettings:
        return replace(self, **kwargs)


@dataclass(frozen=True, slots=True)
class SemanticCacheRecallConfig:
    """Read path knobs. Only used when master ``enabled`` is true."""

    enabled: bool = True
    top_k: int = 5
    min_score: float = 0.0
    types: tuple[str, ...] = ("profile", "semantic", "conversational")
    min_query_chars: int = 12
    timeout_ms: int = 150
    fail_closed: bool = False


@dataclass(frozen=True, slots=True)
class SemanticCacheInjectConfig:
    bag: str = "B"
    key: str = "semantic_memory"
    max_chars: int = 4000
    max_blocks: int = 5
    include_fields: tuple[str, ...] = ("summary", "text")
    order: str = "score_desc"


@dataclass(frozen=True, slots=True)
class SemanticCacheWriteConfig:
    enabled: bool = True
    on_turn_commit: bool = True
    write_explicit_only: bool = True
    write_user_message: bool = False
    write_assistant_summary: bool = False
    default_type: str = "conversational"
    types_allowed: tuple[str, ...] = ("conversational", "profile", "semantic")
    min_chars: int = 24
    max_chars_per_block: int = 2000
    max_blocks_per_turn: int = 3
    ttl_seconds: int = 604800
    async_write: bool = True


@dataclass(frozen=True, slots=True)
class SemanticCacheEmbedConfig:
    """Hints only — embed model/dim are Zeus-owned."""

    prefer_summary_for_write: bool = True


@dataclass(frozen=True, slots=True)
class SemanticCachePrivacyConfig:
    redact_before_write: bool = False
    deny_regex: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticCacheConfig:
    """L0 ``session.semantic_cache`` (ZF-WISH-001). Master default off."""

    enabled: bool = False
    apply_to_modes: tuple[str, ...] = ("agent",)
    recall: SemanticCacheRecallConfig = field(default_factory=SemanticCacheRecallConfig)
    inject: SemanticCacheInjectConfig = field(default_factory=SemanticCacheInjectConfig)
    write: SemanticCacheWriteConfig = field(default_factory=SemanticCacheWriteConfig)
    embed: SemanticCacheEmbedConfig = field(default_factory=SemanticCacheEmbedConfig)
    privacy: SemanticCachePrivacyConfig = field(default_factory=SemanticCachePrivacyConfig)
    # Lab only: body user_id when zeus.auth_mode=none. Ignored when a principal exists.
    dev_user_id: str | None = None

    def with_updates(self, **kwargs: Any) -> SemanticCacheConfig:
        return replace(self, **kwargs)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "apply_to_modes": list(self.apply_to_modes),
            "recall": {
                "enabled": self.recall.enabled,
                "top_k": self.recall.top_k,
                "min_score": self.recall.min_score,
                "types": list(self.recall.types),
                "min_query_chars": self.recall.min_query_chars,
                "timeout_ms": self.recall.timeout_ms,
                "fail_closed": self.recall.fail_closed,
            },
            "inject": {
                "bag": self.inject.bag,
                "key": self.inject.key,
                "max_chars": self.inject.max_chars,
                "max_blocks": self.inject.max_blocks,
                "include_fields": list(self.inject.include_fields),
                "order": self.inject.order,
            },
            "write": {
                "enabled": self.write.enabled,
                "on_turn_commit": self.write.on_turn_commit,
                "write_explicit_only": self.write.write_explicit_only,
                "write_user_message": self.write.write_user_message,
                "write_assistant_summary": self.write.write_assistant_summary,
                "default_type": self.write.default_type,
                "min_chars": self.write.min_chars,
                "max_chars_per_block": self.write.max_chars_per_block,
                "max_blocks_per_turn": self.write.max_blocks_per_turn,
                "ttl_seconds": self.write.ttl_seconds,
                "async": self.write.async_write,
            },
            "embed": {"prefer_summary_for_write": self.embed.prefer_summary_for_write},
            "privacy": {
                "redact_before_write": self.privacy.redact_before_write,
                "deny_regex_count": len(self.privacy.deny_regex),
            },
            "has_dev_user_id": bool(self.dev_user_id),
        }


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
    hub_base_url: str | None = None


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Client-side rate limits (SECURITY §11). Typeahead token bucket defaults."""

    typeahead_enabled: bool = True
    typeahead_rps: float = 10.0
    typeahead_burst: float = 20.0


@dataclass(frozen=True, slots=True)
class LoggingPolicy:
    """Family logger (CHECKLIST D / LOGGING.md). Four levels only."""

    level: str = "info"  # error | info | debug | trace
    redact: bool = True
    otel_enabled: bool = False
    otel_endpoint: str | None = None
    service_name: str = "zeus_client"
    service_version: str | None = None


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    """Optional host identity for report/session stamps. Never invent IP."""

    ip_address: str | None = None


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
    rate_limit: RateLimitPolicy = field(default_factory=RateLimitPolicy)
    logging: LoggingPolicy = field(default_factory=LoggingPolicy)
    client: ClientIdentity = field(default_factory=ClientIdentity)
    chat_requests_dir: str | None = None
    jobs: JobsConfig = field(default_factory=JobsConfig)
    client_floor: str = "client-floor-5"
    allow_degraded_catalog: bool = False
    scope_contracts: Mapping[str, Any] = field(default_factory=dict)
    production_base_id: str | None = None
    # L0 session.semantic_cache — master default false (ZF-WISH-001)
    semantic_cache: SemanticCacheConfig = field(default_factory=SemanticCacheConfig)

    def __repr__(self) -> str:
        # Never dump nested secrets; models already use env-name-only fields.
        return (
            f"RuntimeConfig(profile={self.profile!r}, zeus={self.zeus!r}, "
            f"target={self.target!r}, llm={self.llm!r}, settings={self.settings!r}, "
            f"retry={self.retry!r}, redaction={self.redaction!r}, debug={self.debug!r}, "
            f"rate_limit={self.rate_limit!r}, logging={self.logging!r}, "
            f"client={self.client!r}, chat_requests_dir={self.chat_requests_dir!r}, "
            f"jobs={self.jobs!r}, semantic_cache.enabled={self.semantic_cache.enabled!r})"
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
                "tls_verify": self.zeus.tls_verify,
                "cert_file": self.zeus.cert_file,
                "key_file_env": self.zeus.key_file_env,
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
                "roles": {name: role.to_public_dict() for name, role in self.llm.roles.items()},
            },
            "settings": {
                "ai_process_result": self.settings.ai_process_result,
                "max_rounds": self.settings.max_rounds,
                "force_trace": self.settings.force_trace,
                "mode": self.settings.mode,
                "durable_sessions": self.settings.durable_sessions,
                "soft_require_policy_action": self.settings.soft_require_policy_action,
                "app_output_on_error": self.settings.app_output_on_error,
                # sticky_flags / messages / output_request omitted from public dict
                # when empty; presence of keys only (no secret values).
                "sticky_flag_keys": sorted(str(k) for k in self.settings.sticky_flags),
                "message_keys": sorted(str(k) for k in self.settings.messages),
                "has_output_request": self.settings.output_request is not None,
                "ruleset_id": self.settings.ruleset_id,
                "has_rules": bool(self.settings.rules),
                "ignore_user_tool_path_hints": self.settings.ignore_user_tool_path_hints,
                "force_return_rounds_left": self.settings.force_return_rounds_left,
                "tool_trail_enabled": self.settings.tool_trail_enabled,
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
            "rate_limit": {
                "typeahead_enabled": self.rate_limit.typeahead_enabled,
                "typeahead_rps": self.rate_limit.typeahead_rps,
                "typeahead_burst": self.rate_limit.typeahead_burst,
            },
            "logging": {
                "level": self.logging.level,
                "redact": self.logging.redact,
                "otel_enabled": self.logging.otel_enabled,
                "otel_endpoint": self.logging.otel_endpoint,
                "service_name": self.logging.service_name,
                "service_version": self.logging.service_version,
            },
            "client": {
                "ip_address": self.client.ip_address,
            },
            "chat_requests_dir": self.chat_requests_dir,
            "jobs": {
                "host_url": self.jobs.host_url,
                "watch_transport": self.jobs.watch_transport,
                "models": dict(self.jobs.models),
            },
            "client_floor": self.client_floor,
            "allow_degraded_catalog": self.allow_degraded_catalog,
            "scope_contract_keys": sorted(str(k) for k in self.scope_contracts),
            "production_base_id": self.production_base_id,
            "semantic_cache": self.semantic_cache.to_public_dict(),
        }

    def with_overrides(self, **kwargs: Any) -> RuntimeConfig:
        return replace(self, **kwargs)
