"""Load RuntimeConfig from JSON file + env overlays (ZEUS_CLIENT_*)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from zeus_client.config.models import (
    ClientIdentity,
    ClientSettings,
    DataTarget,
    DebugPolicy,
    JobsConfig,
    LlmProviderConfig,
    LlmRoleConfig,
    LoggingPolicy,
    RateLimitPolicy,
    RedactionPolicy,
    RetryPolicy,
    RuntimeConfig,
    SemanticCacheConfig,
    SemanticCacheEmbedConfig,
    SemanticCacheInjectConfig,
    SemanticCachePrivacyConfig,
    SemanticCacheRecallConfig,
    SemanticCacheWriteConfig,
    ZeusEndpointConfig,
)
from zeus_client.config.profiles import apply_profile
from zeus_client.domain.errors import ConfigError, ErrorCode
from zeus_client.domain.semantic_cache import (
    BLOCK_TYPES,
    DEFAULT_APPLY_TO_MODES,
    DEFAULT_INJECT_KEY,
    ttl_seconds_from,
)

__all__ = ["load_runtime_config", "config_from_mapping"]


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_str_bool_map(raw: Any) -> dict[str, bool]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def _as_str_str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _dig(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = mapping
    for k in keys:
        if not isinstance(cur, Mapping) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _parse_llm_roles(
    raw: Any,
    *,
    default_api_key_env: str,
) -> dict[str, LlmRoleConfig]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, LlmRoleConfig] = {}
    for name, spec in raw.items():
        if not isinstance(spec, Mapping):
            continue
        key_env = spec.get("api_key_env")
        out[str(name)] = LlmRoleConfig(
            model=spec.get("model"),
            api_key_env=str(key_env) if key_env else default_api_key_env,
            base_url=spec.get("base_url"),
            provider=spec.get("provider"),
            temperature=(
                float(spec["temperature"]) if spec.get("temperature") is not None else None
            ),
        )
    return out


def _as_obj_map(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _as_str_tuple(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    if isinstance(raw, str):
        s = raw.strip()
        return (s,) if s else default
    if isinstance(raw, (list, tuple)):
        out = tuple(str(x).strip() for x in raw if str(x).strip())
        return out if out else default
    return default


def _parse_semantic_cache(raw: Any) -> SemanticCacheConfig:
    """L0 ``session.semantic_cache`` — bool or nested object. Default off."""
    if raw is None or raw is False:
        return SemanticCacheConfig()
    if raw is True:
        return SemanticCacheConfig(enabled=True)
    if not isinstance(raw, Mapping):
        return SemanticCacheConfig()
    data = dict(raw)
    recall_raw = _as_obj_map(data.get("recall"))
    inject_raw = _as_obj_map(data.get("inject"))
    write_raw = _as_obj_map(data.get("write"))
    embed_raw = _as_obj_map(data.get("embed"))
    privacy_raw = _as_obj_map(data.get("privacy"))
    types_default = ("profile", "semantic", "conversational")
    recall_types = _as_str_tuple(recall_raw.get("types"), types_default)
    recall_types = tuple(t for t in recall_types if t in BLOCK_TYPES) or types_default
    allowed = _as_str_tuple(write_raw.get("types_allowed"), BLOCK_TYPES)
    allowed = tuple(t for t in allowed if t in BLOCK_TYPES) or BLOCK_TYPES
    async_raw = write_raw.get("async")
    if async_raw is None:
        async_raw = write_raw.get("async_write")
    order = str(inject_raw.get("order") or "score_desc").strip().lower()
    if order not in {"score_desc", "recency"}:
        order = "score_desc"
    bag = str(inject_raw.get("bag") or "B").strip() or "B"
    key = str(inject_raw.get("key") or DEFAULT_INJECT_KEY).strip() or DEFAULT_INJECT_KEY
    default_type = str(write_raw.get("default_type") or "conversational").strip().lower()
    if default_type not in BLOCK_TYPES:
        default_type = "conversational"
    deny = privacy_raw.get("deny_regex")
    deny_tuple: tuple[str, ...] = ()
    if isinstance(deny, (list, tuple)):
        deny_tuple = tuple(str(x) for x in deny if x)
    elif isinstance(deny, str) and deny.strip():
        deny_tuple = (deny.strip(),)
    dev_uid = data.get("dev_user_id")
    return SemanticCacheConfig(
        enabled=_as_bool(data.get("enabled"), False),
        apply_to_modes=_as_str_tuple(data.get("apply_to_modes"), DEFAULT_APPLY_TO_MODES),
        recall=SemanticCacheRecallConfig(
            enabled=_as_bool(recall_raw.get("enabled"), True),
            top_k=int(recall_raw.get("top_k", 5)),
            min_score=float(recall_raw.get("min_score", 0.0)),
            types=recall_types,
            min_query_chars=int(recall_raw.get("min_query_chars", 12)),
            timeout_ms=int(recall_raw.get("timeout_ms", 150)),
            fail_closed=_as_bool(recall_raw.get("fail_closed"), False),
        ),
        inject=SemanticCacheInjectConfig(
            bag=bag,
            key=key,
            max_chars=int(inject_raw.get("max_chars", 4000)),
            max_blocks=int(inject_raw.get("max_blocks", 5)),
            include_fields=_as_str_tuple(inject_raw.get("include_fields"), ("summary", "text")),
            order=order,
        ),
        write=SemanticCacheWriteConfig(
            enabled=_as_bool(write_raw.get("enabled"), True),
            on_turn_commit=_as_bool(write_raw.get("on_turn_commit"), True),
            write_explicit_only=_as_bool(write_raw.get("write_explicit_only"), True),
            write_user_message=_as_bool(write_raw.get("write_user_message"), False),
            write_assistant_summary=_as_bool(write_raw.get("write_assistant_summary"), False),
            default_type=default_type,
            types_allowed=allowed,
            min_chars=int(write_raw.get("min_chars", 24)),
            max_chars_per_block=int(write_raw.get("max_chars_per_block", 2000)),
            max_blocks_per_turn=int(write_raw.get("max_blocks_per_turn", 3)),
            ttl_seconds=ttl_seconds_from(write_raw.get("ttl_seconds"), default=604800),
            async_write=_as_bool(async_raw, True),
        ),
        embed=SemanticCacheEmbedConfig(
            prefer_summary_for_write=_as_bool(embed_raw.get("prefer_summary_for_write"), True),
        ),
        privacy=SemanticCachePrivacyConfig(
            redact_before_write=_as_bool(privacy_raw.get("redact_before_write"), False),
            deny_regex=deny_tuple,
        ),
        dev_user_id=str(dev_uid).strip() or None if dev_uid else None,
    )


def _as_rules_map(raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return None
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _parse_client_settings(settings: Mapping[str, Any]) -> ClientSettings:
    return ClientSettings(
        ai_process_result=_as_bool(settings.get("ai_process_result"), False),
        max_rounds=int(settings.get("max_rounds", 8)),
        force_trace=_as_bool(settings.get("force_trace"), False),
        mode=str(settings.get("mode", "analytics")),
        durable_sessions=_as_bool(settings.get("durable_sessions"), True),
        sticky_flags=_as_str_bool_map(settings.get("sticky_flags")),
        messages=_as_str_str_map(settings.get("messages")),
        soft_require_policy_action=_as_bool(settings.get("soft_require_policy_action"), True),
        app_output_on_error=str(settings.get("app_output_on_error") or "strip"),
        output_request=(
            dict(settings["output_request"])
            if isinstance(settings.get("output_request"), dict)
            else None
        ),
        rules=_as_rules_map(settings.get("rules")),
        tenant_rules=_as_rules_map(settings.get("tenant_rules")),
        override_defaults=_as_bool(settings.get("override_defaults"), False),
        company_context=settings.get("company_context"),
        locale=settings.get("locale"),
        language=settings.get("language"),
        timezone=settings.get("timezone"),
        channel=settings.get("channel"),
        market=settings.get("market"),
        deployment_id=settings.get("deployment_id"),
        ruleset_id=settings.get("ruleset_id"),
        force_return_rounds_left=(
            int(settings["force_return_rounds_left"])
            if settings.get("force_return_rounds_left") is not None
            else 1
        ),
        ignore_user_tool_path_hints=_as_bool(settings.get("ignore_user_tool_path_hints"), True),
        tool_trail_enabled=_as_bool(settings.get("tool_trail_enabled"), True),
        tool_trail_inject=_as_bool(settings.get("tool_trail_inject"), True),
        tool_trail_max_entries=int(settings.get("tool_trail_max_entries", 16)),
    )


def _parse_jobs(raw: Any) -> JobsConfig:
    if not isinstance(raw, Mapping):
        return JobsConfig()
    models = raw.get("models")
    return JobsConfig(
        host_url=str(raw["host_url"]) if raw.get("host_url") else None,
        watch_transport="sse",
        models=dict(models) if isinstance(models, Mapping) else {},
    )


def config_from_mapping(data: Mapping[str, Any], *, profile: str | None = None) -> RuntimeConfig:
    """Build RuntimeConfig from a plain mapping (file JSON shape)."""

    def _map(key: str) -> dict[str, Any]:
        raw = data.get(key)
        return dict(raw) if isinstance(raw, Mapping) else {}

    z: dict[str, Any] = _map("zeus")
    t: dict[str, Any] = _map("target")
    # V1 samples key compatibility
    if not t and isinstance(data.get("samples"), Mapping):
        samples = dict(data["samples"])  # type: ignore[arg-type]
        t = {
            "bucket": samples.get("bucket", "yelp-data"),
            "scope": samples.get("scope", "_default"),
            "collection": samples.get("collection", "_default"),
        }
    llm: dict[str, Any] = _map("llm")
    settings: dict[str, Any] = _map("settings")
    retry: dict[str, Any] = _map("retry")
    redaction: dict[str, Any] = _map("redaction")
    debug: dict[str, Any] = _map("debug")
    rate_limit: dict[str, Any] = _map("rate_limit")
    logging_raw: dict[str, Any] = _map("logging")
    client_raw: dict[str, Any] = _map("client")
    jobs_raw: dict[str, Any] = _map("jobs")
    session_raw: dict[str, Any] = _map("session")
    default_key_env = str(llm.get("api_key_env", "XAI_API_KEY"))
    roles = _parse_llm_roles(llm.get("roles"), default_api_key_env=default_key_env)

    auth_mode = str(z.get("auth_mode", "none")).lower()
    if auth_mode not in ("none", "basic", "bearer", "session", "certificate"):
        raise ConfigError(
            code=ErrorCode.ZEUS_AUTH_MODE_INVALID,
            component="config.loader",
            public_message=f"zeus.auth_mode invalid: {auth_mode!r}",
        )

    url = str(z.get("url") or z.get("base_url") or "http://127.0.0.1:8080").rstrip("/")
    if not url:
        raise ConfigError(
            code=ErrorCode.ZEUS_URL_MISSING,
            component="config.loader",
            public_message="zeus.url missing or empty",
        )

    cfg = RuntimeConfig(
        profile=str(profile or data.get("profile") or "development"),
        zeus=ZeusEndpointConfig(
            url=url,
            auth_mode=auth_mode,  # type: ignore[arg-type]
            username=z.get("username"),
            password_env=z.get("password_env") or z.get("password_env_name"),
            token_env=z.get("token_env") or z.get("token_env_name"),
            timeout_s=float(z.get("timeout_s", 30.0)),
            tls_verify=_as_bool(z.get("tls_verify", z.get("verify_tls", True)), default=True),
            scope_credentials=(
                {
                    str(k): dict(v)
                    for k, v in z["scope_credentials"].items()
                    if isinstance(v, Mapping)
                }
                if isinstance(z.get("scope_credentials"), Mapping)
                else {}
            ),
            cert_file=z.get("cert_file"),
            key_file=z.get("key_file"),
            key_file_env=z.get("key_file_env"),
        ),
        target=DataTarget(
            bucket=str(t.get("bucket", "yelp-data")),
            scope=str(t.get("scope", "_default")),
            collection=str(t.get("collection", "_default")),
        ),
        llm=LlmProviderConfig(
            provider=str(llm.get("provider", "xai")),
            base_url=str(llm.get("base_url", "https://api.x.ai/v1")).rstrip("/"),
            model=str(llm.get("model", "grok-4-1-non-reasoning")),
            api_key_env=default_key_env,
            context_window_tokens=int(llm.get("context_window_tokens", 128_000)),
            context_soft_limit=float(llm.get("context_soft_limit", 0.8)),
            timeout_s=float(llm.get("timeout_s", 120.0)),
            roles=roles,
        ),
        settings=_parse_client_settings(settings),
        retry=RetryPolicy(
            max_attempts=int(retry.get("max_attempts", 3)),
            base_delay_ms=int(retry.get("base_delay_ms", 200)),
            max_delay_ms=int(retry.get("max_delay_ms", 5_000)),
            jitter=_as_bool(retry.get("jitter"), True),
        ),
        redaction=RedactionPolicy(
            enabled=_as_bool(redaction.get("enabled"), True),
            preview_max_chars=int(redaction.get("preview_max_chars", 2048)),
        ),
        debug=DebugPolicy(
            detective_briefing=_as_bool(debug.get("detective_briefing"), True),
            capture_bodies=_as_bool(debug.get("capture_bodies"), False),
            transport_replay=_as_bool(debug.get("transport_replay"), True),
        ),
        rate_limit=RateLimitPolicy(
            typeahead_enabled=_as_bool(rate_limit.get("typeahead_enabled"), True),
            typeahead_rps=float(rate_limit.get("typeahead_rps", 10.0)),
            typeahead_burst=float(rate_limit.get("typeahead_burst", 20.0)),
        ),
        logging=LoggingPolicy(
            level=str(logging_raw.get("level") or "info").strip().lower(),
            redact=_as_bool(logging_raw.get("redact"), True),
            otel_enabled=_as_bool(logging_raw.get("otel_enabled"), False),
            otel_endpoint=(
                str(logging_raw["otel_endpoint"]).strip()
                if logging_raw.get("otel_endpoint")
                else None
            ),
            service_name=str(logging_raw.get("service_name") or "zeus_client"),
            service_version=(
                str(logging_raw["service_version"]) if logging_raw.get("service_version") else None
            ),
        ),
        client=ClientIdentity(
            ip_address=(
                str(client_raw["ip_address"]).strip() or None
                if client_raw.get("ip_address")
                else None
            ),
        ),
        chat_requests_dir=data.get("chat_requests_dir"),
        jobs=_parse_jobs(jobs_raw),
        semantic_cache=_parse_semantic_cache(session_raw.get("semantic_cache")),
        client_floor=str(data.get("client_floor") or "client-floor-5"),
        allow_degraded_catalog=_as_bool(data.get("allow_degraded_catalog"), False),
        production_base_id=(
            str(data["production_base_id"])
            if data.get("production_base_id")
            else (
                str(data["catalog"]["production_base_id"])
                if isinstance(data.get("catalog"), Mapping)
                and data["catalog"].get("production_base_id")
                else None
            )
        ),
        scope_contracts=(
            dict(data["scope_contracts"])
            if isinstance(data.get("scope_contracts"), Mapping)
            else (
                dict(z["scope_contracts"]) if isinstance(z.get("scope_contracts"), Mapping) else {}
            )
        ),
    )
    return apply_profile(cfg, cfg.profile)


def _apply_env(cfg: RuntimeConfig, env: Mapping[str, str]) -> RuntimeConfig:
    """Overlay ZEUS_CLIENT_* and a few common Zeus/LLM env names."""
    z = cfg.zeus
    llm = cfg.llm
    settings = cfg.settings
    target = cfg.target

    if url := env.get("ZEUS_CLIENT_URL") or env.get("ZEUS_URL"):
        z = ZeusEndpointConfig(
            url=url.rstrip("/"),
            auth_mode=z.auth_mode,
            username=env.get("ZEUS_CLIENT_USERNAME", z.username),
            password_env=env.get("ZEUS_CLIENT_PASSWORD_ENV", z.password_env),
            token_env=env.get("ZEUS_CLIENT_TOKEN_ENV", z.token_env),
            timeout_s=float(env.get("ZEUS_CLIENT_TIMEOUT_S", z.timeout_s)),
            tls_verify=_as_bool(env.get("ZEUS_CLIENT_TLS_VERIFY"), z.tls_verify),
            scope_credentials=z.scope_credentials,
            cert_file=z.cert_file,
            key_file=z.key_file,
            key_file_env=z.key_file_env,
        )
    else:
        # partial field overrides
        z = ZeusEndpointConfig(
            url=z.url,
            auth_mode=(env.get("ZEUS_CLIENT_AUTH_MODE", z.auth_mode) or z.auth_mode),  # type: ignore[arg-type]
            username=env.get("ZEUS_CLIENT_USERNAME", z.username),
            password_env=env.get("ZEUS_CLIENT_PASSWORD_ENV", z.password_env),
            token_env=env.get("ZEUS_CLIENT_TOKEN_ENV", z.token_env),
            timeout_s=float(env.get("ZEUS_CLIENT_TIMEOUT_S", z.timeout_s)),
            tls_verify=_as_bool(env.get("ZEUS_CLIENT_TLS_VERIFY"), z.tls_verify),
            scope_credentials=z.scope_credentials,
            cert_file=z.cert_file,
            key_file=z.key_file,
            key_file_env=z.key_file_env,
        )
        if z.auth_mode not in ("none", "basic", "bearer", "session", "certificate"):
            raise ConfigError(
                code=ErrorCode.ZEUS_AUTH_MODE_INVALID,
                component="config.loader",
                public_message=f"zeus.auth_mode invalid: {z.auth_mode!r}",
            )

    if (
        env.get("ZEUS_CLIENT_BUCKET")
        or env.get("ZEUS_CLIENT_SCOPE")
        or env.get("ZEUS_CLIENT_COLLECTION")
    ):
        target = DataTarget(
            bucket=env.get("ZEUS_CLIENT_BUCKET", target.bucket),
            scope=env.get("ZEUS_CLIENT_SCOPE", target.scope),
            collection=env.get("ZEUS_CLIENT_COLLECTION", target.collection),
        )

    llm = LlmProviderConfig(
        provider=env.get("ZEUS_CLIENT_LLM_PROVIDER", llm.provider),
        base_url=env.get("ZEUS_CLIENT_LLM_BASE_URL", llm.base_url).rstrip("/"),
        model=env.get("ZEUS_CLIENT_LLM_MODEL", llm.model),
        api_key_env=env.get("ZEUS_CLIENT_LLM_API_KEY_ENV", llm.api_key_env),
        context_window_tokens=int(
            env.get("ZEUS_CLIENT_LLM_CONTEXT_WINDOW", llm.context_window_tokens)
        ),
        context_soft_limit=float(
            env.get("ZEUS_CLIENT_LLM_CONTEXT_SOFT_LIMIT", llm.context_soft_limit)
        ),
        timeout_s=float(env.get("ZEUS_CLIENT_LLM_TIMEOUT_S", llm.timeout_s)),
        roles=llm.roles,
    )

    if "ZEUS_CLIENT_AI_PROCESS_RESULT" in env or any(
        k in env
        for k in (
            "ZEUS_CLIENT_MAX_ROUNDS",
            "ZEUS_CLIENT_FORCE_TRACE",
            "ZEUS_CLIENT_MODE",
            "ZEUS_CLIENT_DURABLE_SESSIONS",
        )
    ):
        settings = settings.with_updates(
            ai_process_result=(
                _as_bool(env.get("ZEUS_CLIENT_AI_PROCESS_RESULT"), settings.ai_process_result)
                if "ZEUS_CLIENT_AI_PROCESS_RESULT" in env
                else settings.ai_process_result
            ),
            max_rounds=int(env.get("ZEUS_CLIENT_MAX_ROUNDS", settings.max_rounds)),
            force_trace=_as_bool(env.get("ZEUS_CLIENT_FORCE_TRACE"), settings.force_trace),
            mode=env.get("ZEUS_CLIENT_MODE", settings.mode),
            durable_sessions=_as_bool(
                env.get("ZEUS_CLIENT_DURABLE_SESSIONS"), settings.durable_sessions
            ),
        )

    chat_dir = env.get("ZEUS_CLIENT_CHAT_REQUESTS_DIR", cfg.chat_requests_dir)
    profile = env.get("ZEUS_CLIENT_PROFILE", cfg.profile)
    client_floor = env.get("ZEUS_CLIENT_FLOOR", cfg.client_floor)
    log_pol = cfg.logging
    if any(
        k in env
        for k in (
            "ZEUS_CLIENT_LOG_LEVEL",
            "ZEUS_CLIENT_LOG_REDACT",
            "ZEUS_CLIENT_OTEL_ENABLED",
            "ZEUS_CLIENT_OTEL_ENDPOINT",
            "ZEUS_CLIENT_SERVICE_NAME",
            "ZEUS_CLIENT_SERVICE_VERSION",
        )
    ):
        log_pol = LoggingPolicy(
            level=str(env.get("ZEUS_CLIENT_LOG_LEVEL", log_pol.level)).strip().lower(),
            redact=_as_bool(env.get("ZEUS_CLIENT_LOG_REDACT"), log_pol.redact)
            if "ZEUS_CLIENT_LOG_REDACT" in env
            else log_pol.redact,
            otel_enabled=_as_bool(env.get("ZEUS_CLIENT_OTEL_ENABLED"), log_pol.otel_enabled)
            if "ZEUS_CLIENT_OTEL_ENABLED" in env
            else log_pol.otel_enabled,
            otel_endpoint=(
                str(env["ZEUS_CLIENT_OTEL_ENDPOINT"]).strip() or None
                if "ZEUS_CLIENT_OTEL_ENDPOINT" in env
                else log_pol.otel_endpoint
            ),
            service_name=env.get("ZEUS_CLIENT_SERVICE_NAME", log_pol.service_name),
            service_version=env.get("ZEUS_CLIENT_SERVICE_VERSION", log_pol.service_version),
        )
    ident = cfg.client
    if "ZEUS_CLIENT_IP" in env:
        ident = ClientIdentity(ip_address=str(env.get("ZEUS_CLIENT_IP") or "").strip() or None)
    jobs = cfg.jobs
    if host := env.get("ZEUS_CLIENT_JOBS_HOST_URL"):
        jobs = JobsConfig(
            host_url=host,
            watch_transport=jobs.watch_transport,
            models=jobs.models,
        )

    semantic_cache = cfg.semantic_cache
    if "ZEUS_CLIENT_SEMANTIC_CACHE" in env:
        semantic_cache = semantic_cache.with_updates(
            enabled=_as_bool(env.get("ZEUS_CLIENT_SEMANTIC_CACHE"), False)
        )

    out = cfg.with_overrides(
        profile=profile,
        zeus=z,
        target=target,
        llm=llm,
        settings=settings,
        logging=log_pol,
        client=ident,
        chat_requests_dir=chat_dir,
        jobs=jobs,
        client_floor=client_floor,
        semantic_cache=semantic_cache,
    )
    return apply_profile(out, out.profile)


def load_runtime_config(
    path: str | Path | None = None,
    *,
    profile: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """
    Load config from optional JSON path, then apply profile + env overlays.

    ``env`` defaults to ``os.environ``. Never reads secret *values* into the
    config object — only env *names* for later SecretStore resolution.
    """
    environ = dict(env) if env is not None else dict(os.environ)
    data: dict[str, Any] = {}
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise ConfigError(
                code=ErrorCode.CONFIG_PATH_NOT_FOUND,
                component="config.loader",
                public_message=f"config path not found: {p}",
                details={"path": str(p)},
            )
        try:
            raw = p.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                code=ErrorCode.CONFIG_PARSE_FAILED,
                component="config.loader",
                public_message="config file parse failed",
                details={"path": str(p), "error": str(exc)},
            ) from exc
        if not isinstance(parsed, dict):
            raise ConfigError(
                code=ErrorCode.CONFIG_INVALID,
                component="config.loader",
                public_message="config mapping invalid",
            )
        data = parsed

    prof = profile or environ.get("ZEUS_CLIENT_PROFILE") or data.get("profile") or "development"
    cfg = config_from_mapping(data, profile=str(prof))
    return _apply_env(cfg, environ)
