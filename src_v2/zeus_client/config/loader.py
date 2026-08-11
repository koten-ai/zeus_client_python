"""Load RuntimeConfig from JSON file + env overlays (ZEUS_CLIENT_*)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from zeus_client_v2.config.models import (
    AuthMode,
    ClientSettings,
    DataTarget,
    DebugPolicy,
    LlmProviderConfig,
    RedactionPolicy,
    RetryPolicy,
    RuntimeConfig,
    ZeusEndpointConfig,
)
from zeus_client_v2.config.profiles import apply_profile
from zeus_client_v2.domain.errors import ConfigError, ErrorCode

__all__ = ["load_runtime_config", "config_from_mapping"]


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _dig(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = mapping
    for k in keys:
        if not isinstance(cur, Mapping) or k not in cur:
            return default
        cur = cur[k]
    return cur


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

    auth_mode = str(z.get("auth_mode", "none")).lower()
    if auth_mode not in ("none", "basic", "bearer", "session"):
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
            api_key_env=str(llm.get("api_key_env", "XAI_API_KEY")),
            context_window_tokens=int(llm.get("context_window_tokens", 128_000)),
            context_soft_limit=float(llm.get("context_soft_limit", 0.8)),
            timeout_s=float(llm.get("timeout_s", 120.0)),
        ),
        settings=ClientSettings(
            ai_process_result=_as_bool(settings.get("ai_process_result"), True),
            max_rounds=int(settings.get("max_rounds", 8)),
            force_trace=_as_bool(settings.get("force_trace"), False),
            mode=str(settings.get("mode", "analytics")),
            durable_sessions=_as_bool(settings.get("durable_sessions"), True),
        ),
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
        chat_requests_dir=data.get("chat_requests_dir"),
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
        )
        if z.auth_mode not in ("none", "basic", "bearer", "session"):
            raise ConfigError(
                code=ErrorCode.ZEUS_AUTH_MODE_INVALID,
                component="config.loader",
                public_message=f"zeus.auth_mode invalid: {z.auth_mode!r}",
            )

    if env.get("ZEUS_CLIENT_BUCKET") or env.get("ZEUS_CLIENT_SCOPE") or env.get("ZEUS_CLIENT_COLLECTION"):
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
    )

    if "ZEUS_CLIENT_AI_PROCESS_RESULT" in env:
        settings = ClientSettings(
            ai_process_result=_as_bool(env.get("ZEUS_CLIENT_AI_PROCESS_RESULT"), True),
            max_rounds=int(env.get("ZEUS_CLIENT_MAX_ROUNDS", settings.max_rounds)),
            force_trace=_as_bool(
                env.get("ZEUS_CLIENT_FORCE_TRACE"), settings.force_trace
            ),
            mode=env.get("ZEUS_CLIENT_MODE", settings.mode),
            durable_sessions=_as_bool(
                env.get("ZEUS_CLIENT_DURABLE_SESSIONS"), settings.durable_sessions
            ),
        )
    elif any(
        k in env
        for k in (
            "ZEUS_CLIENT_MAX_ROUNDS",
            "ZEUS_CLIENT_FORCE_TRACE",
            "ZEUS_CLIENT_MODE",
            "ZEUS_CLIENT_DURABLE_SESSIONS",
        )
    ):
        settings = ClientSettings(
            ai_process_result=settings.ai_process_result,
            max_rounds=int(env.get("ZEUS_CLIENT_MAX_ROUNDS", settings.max_rounds)),
            force_trace=_as_bool(
                env.get("ZEUS_CLIENT_FORCE_TRACE"), settings.force_trace
            ),
            mode=env.get("ZEUS_CLIENT_MODE", settings.mode),
            durable_sessions=_as_bool(
                env.get("ZEUS_CLIENT_DURABLE_SESSIONS"), settings.durable_sessions
            ),
        )

    chat_dir = env.get("ZEUS_CLIENT_CHAT_REQUESTS_DIR", cfg.chat_requests_dir)
    profile = env.get("ZEUS_CLIENT_PROFILE", cfg.profile)

    out = cfg.with_overrides(
        profile=profile,
        zeus=z,
        target=target,
        llm=llm,
        settings=settings,
        chat_requests_dir=chat_dir,
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
