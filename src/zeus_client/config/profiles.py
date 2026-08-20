"""Named profiles: development / production / ci / hub."""

from __future__ import annotations

from zeus_client.config.models import (
    DebugPolicy,
    LoggingPolicy,
    RedactionPolicy,
    RuntimeConfig,
)
from zeus_client.domain.errors import ConfigError, ErrorCode

__all__ = ["PROFILES", "apply_profile", "list_profiles", "validate_production_security"]

PROFILES = ("development", "production", "ci", "hub")


def list_profiles() -> tuple[str, ...]:
    return PROFILES


def validate_production_security(cfg: RuntimeConfig) -> None:
    """Fail closed on insecure production combos (SECURITY §23 / §14).

    Raises:
        ConfigError: when ``auth_mode=none`` or TLS verify is disabled.
    """
    if cfg.zeus.auth_mode == "none":
        raise ConfigError(
            code=ErrorCode.CONFIG_INVALID,
            component="config.profiles",
            public_message=(
                "production profile rejects zeus.auth_mode=none; use basic, bearer, or session"
            ),
        )
    if cfg.zeus.tls_verify is False:
        raise ConfigError(
            code=ErrorCode.CONFIG_INVALID,
            component="config.profiles",
            public_message=(
                "production profile rejects zeus.tls_verify=false; TLS verification is required"
            ),
        )


def apply_profile(base: RuntimeConfig, profile: str) -> RuntimeConfig:
    """Return a new RuntimeConfig with profile-specific policy defaults."""
    name = (profile or "development").strip().lower()
    if name in ("dev", "development"):
        return base.with_overrides(
            profile="development",
            redaction=RedactionPolicy(enabled=True, preview_max_chars=16_384),
            debug=DebugPolicy(
                detective_briefing=True,
                capture_bodies=True,
                transport_replay=True,
            ),
            logging=LoggingPolicy(
                level=base.logging.level if base.logging.level != "info" else "debug",
                redact=base.logging.redact,
                otel_enabled=base.logging.otel_enabled,
                otel_endpoint=base.logging.otel_endpoint,
                service_name=base.logging.service_name,
                service_version=base.logging.service_version,
            ),
        )
    if name in ("prod", "production"):
        out = base.with_overrides(
            profile="production",
            redaction=RedactionPolicy(enabled=True, preview_max_chars=2_048),
            debug=DebugPolicy(
                detective_briefing=True,
                capture_bodies=False,
                transport_replay=True,
            ),
            settings=base.settings.with_updates(ai_process_result=False),
            logging=LoggingPolicy(
                level=(
                    base.logging.level
                    if base.logging.level in {"error", "info", "debug", "trace"}
                    else "info"
                ),
                redact=True,
                otel_enabled=bool(base.logging.otel_endpoint) or base.logging.otel_enabled,
                otel_endpoint=base.logging.otel_endpoint,
                service_name=base.logging.service_name,
                service_version=base.logging.service_version,
            ),
        )
        validate_production_security(out)
        return out
    if name == "ci":
        return base.with_overrides(
            profile="ci",
            redaction=RedactionPolicy(enabled=True, preview_max_chars=4_096),
            debug=DebugPolicy(
                detective_briefing=True,
                capture_bodies=False,
                transport_replay=True,
            ),
            settings=base.settings.with_updates(ai_process_result=False),
        )
    if name == "hub":
        return base.with_overrides(
            profile="hub",
            redaction=RedactionPolicy(enabled=True, preview_max_chars=16_384),
            debug=DebugPolicy(
                detective_briefing=True,
                capture_bodies=True,
                transport_replay=True,
            ),
            settings=base.settings.with_updates(ai_process_result=True),
        )
    # Unknown profile → treat as development but keep requested name for diagnostics.
    return base.with_overrides(
        profile=name,
        redaction=RedactionPolicy(enabled=True, preview_max_chars=16_384),
        debug=DebugPolicy(
            detective_briefing=True,
            capture_bodies=True,
            transport_replay=True,
        ),
    )
