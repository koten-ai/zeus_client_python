"""Named profiles: development / production / ci."""

from __future__ import annotations

from zeus_client_v2.config.models import (
    DebugPolicy,
    RedactionPolicy,
    RuntimeConfig,
)

__all__ = ["PROFILES", "apply_profile", "list_profiles"]

PROFILES = ("development", "production", "ci")


def list_profiles() -> tuple[str, ...]:
    return PROFILES


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
        )
    if name in ("prod", "production"):
        return base.with_overrides(
            profile="production",
            redaction=RedactionPolicy(enabled=True, preview_max_chars=2_048),
            debug=DebugPolicy(
                detective_briefing=True,
                capture_bodies=False,
                transport_replay=True,
            ),
        )
    if name == "ci":
        return base.with_overrides(
            profile="ci",
            redaction=RedactionPolicy(enabled=True, preview_max_chars=4_096),
            debug=DebugPolicy(
                detective_briefing=True,
                capture_bodies=False,
                transport_replay=True,
            ),
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
