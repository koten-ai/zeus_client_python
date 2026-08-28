"""ZCP-112 — DebugPolicy.rewind + ZEUS_REWIND loader overlay."""

from __future__ import annotations

from zeus_client.config.loader import config_from_mapping
from zeus_client.config.models import DebugPolicy


def test_debug_policy_rewind_default_off() -> None:
    assert DebugPolicy().rewind is False


def test_loader_debug_rewind_from_mapping() -> None:
    cfg = config_from_mapping({"debug": {"rewind": True}, "profile": "ci"})
    assert cfg.debug.rewind is True


def test_loader_settings_rewind_alias() -> None:
    cfg = config_from_mapping({"settings": {"rewind": True}, "profile": "ci"})
    assert cfg.debug.rewind is True


def test_loader_zeus_rewind_env() -> None:
    cfg = config_from_mapping({"profile": "ci"}, profile="ci")
    from zeus_client.config.loader import _apply_env

    out = _apply_env(cfg, {"ZEUS_REWIND": "true"})
    assert out.debug.rewind is True


def test_loader_zeus_rewind_env_off() -> None:
    cfg = config_from_mapping({"debug": {"rewind": True}, "profile": "ci"})
    from zeus_client.config.loader import _apply_env

    out = _apply_env(cfg, {"ZEUS_REWIND": "0"})
    assert out.debug.rewind is False


def test_profile_preserves_rewind() -> None:
    cfg = config_from_mapping({"debug": {"rewind": True}, "profile": "development"})
    from zeus_client.config.loader import _apply_env

    out = _apply_env(cfg, {})
    assert out.debug.rewind is True
    assert out.profile == "development"
