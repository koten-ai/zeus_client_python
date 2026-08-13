"""Production profile hard rejects (SECURITY §23) — ZCP-36."""

from __future__ import annotations

import pytest

from zeus_client.config.models import RuntimeConfig, ZeusEndpointConfig
from zeus_client.config.profiles import apply_profile
from zeus_client.domain.errors import ConfigError, ErrorCode


def test_production_rejects_auth_mode_none() -> None:
    base = RuntimeConfig(zeus=ZeusEndpointConfig(auth_mode="none", tls_verify=True))
    with pytest.raises(ConfigError) as ei:
        apply_profile(base, "production")
    assert ei.value.code is ErrorCode.CONFIG_INVALID
    assert "auth_mode=none" in ei.value.public_message


def test_production_rejects_tls_verify_off() -> None:
    base = RuntimeConfig(zeus=ZeusEndpointConfig(auth_mode="basic", username="u", tls_verify=False))
    with pytest.raises(ConfigError) as ei:
        apply_profile(base, "production")
    assert ei.value.code is ErrorCode.CONFIG_INVALID
    assert "tls_verify" in ei.value.public_message


def test_production_accepts_basic_with_tls() -> None:
    base = RuntimeConfig(
        zeus=ZeusEndpointConfig(
            auth_mode="basic",
            username="admin",
            password_env="ZEUS_PASSWORD",
            tls_verify=True,
        )
    )
    out = apply_profile(base, "production")
    assert out.profile == "production"
    assert out.debug.capture_bodies is False
    assert out.zeus.auth_mode == "basic"
    assert out.zeus.tls_verify is True


def test_development_still_allows_auth_mode_none() -> None:
    base = RuntimeConfig(zeus=ZeusEndpointConfig(auth_mode="none"))
    out = apply_profile(base, "development")
    assert out.profile == "development"
    assert out.zeus.auth_mode == "none"


def test_ci_still_allows_auth_mode_none() -> None:
    base = RuntimeConfig(zeus=ZeusEndpointConfig(auth_mode="none"))
    out = apply_profile(base, "ci")
    assert out.profile == "ci"
    assert out.zeus.auth_mode == "none"
