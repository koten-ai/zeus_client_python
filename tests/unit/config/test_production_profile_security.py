"""Production profile hard rejects (SECURITY §23) — ZCP-36."""

from __future__ import annotations

import pytest

from zeus_client.config.loader import load_runtime_config
from zeus_client.config.models import M2MClientConfig, RuntimeConfig, ZeusEndpointConfig
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


def test_production_accepts_m2m_with_tls() -> None:
    base = RuntimeConfig(
        zeus=ZeusEndpointConfig(
            auth_mode="m2m",
            tls_verify=True,
            m2m=M2MClientConfig(
                issuer="https://idp.example/",
                audience="https://zeus.example",
                client_id="zeus-nightly",
                client_secret_env="ZEUS_M2M_CLIENT_SECRET",
            ),
        )
    )
    out = apply_profile(base, "production")
    assert out.profile == "production"
    assert out.zeus.auth_mode == "m2m"
    assert "s3cret" not in repr(out)


def test_production_accepts_pat_with_tls() -> None:
    base = RuntimeConfig(
        zeus=ZeusEndpointConfig(auth_mode="pat", token_env="ZEUS_PAT", tls_verify=True)
    )
    out = apply_profile(base, "production")
    assert out.profile == "production"
    assert out.zeus.auth_mode == "pat"


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
    assert out.settings.ai_process_result is False


def test_development_still_allows_auth_mode_none() -> None:
    base = RuntimeConfig(zeus=ZeusEndpointConfig(auth_mode="none"))
    out = apply_profile(base, "development")
    assert out.profile == "development"
    assert out.zeus.auth_mode == "none"
    assert out.settings.ai_process_result is False


def test_hub_profile_insight_default() -> None:
    out = apply_profile(RuntimeConfig(), "hub")
    assert out.profile == "hub"
    assert out.settings.ai_process_result is True
    assert out.debug.capture_bodies is True


def test_ci_still_allows_auth_mode_none() -> None:
    base = RuntimeConfig(zeus=ZeusEndpointConfig(auth_mode="none"))
    out = apply_profile(base, "ci")
    assert out.profile == "ci"
    assert out.zeus.auth_mode == "none"


def test_loader_accepts_auth_mode_pat() -> None:
    cfg = load_runtime_config(env={"ZEUS_CLIENT_AUTH_MODE": "pat"})
    assert cfg.zeus.auth_mode == "pat"


def test_loader_m2m_stores_secret_env_name_only(tmp_path) -> None:
    import json

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "zeus": {
                    "auth_mode": "m2m",
                    "m2m": {
                        "issuer": "https://idp.example/",
                        "audience": "https://zeus.example",
                        "client_id": "zeus-nightly",
                        "client_secret_env": "ZEUS_M2M_CLIENT_SECRET",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_runtime_config(path, env={})
    assert cfg.zeus.auth_mode == "m2m"
    assert cfg.zeus.m2m.issuer == "https://idp.example/"
    assert cfg.zeus.m2m.client_secret_env == "ZEUS_M2M_CLIENT_SECRET"
    assert cfg.zeus.m2m.scope == "zeus.read zeus.traverse"
    assert "s3cret" not in repr(cfg)
