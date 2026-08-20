"""Named rules merge / freeze (CHECKLIST C)."""

from __future__ import annotations

import pytest

from zeus_client.application.control_plane_inject import (
    prepare_settings,
    truncate_company_context,
    validate_output_request,
)
from zeus_client.config.models import ClientSettings
from zeus_client.domain.policy import JAILBREAK_RULE_IDS
from zeus_client.domain.rules import (
    append_session_rules,
    freeze_session_rules,
    merge_rules,
    merge_rules_frozen,
)


def test_default_jailbreak_keys_present() -> None:
    pack = merge_rules()
    for k in JAILBREAK_RULE_IDS:
        assert k in pack


def test_request_rules_override_text() -> None:
    pack = merge_rules(request_rules={"no_invent_data": "Custom invent law."})
    assert pack["no_invent_data"] == "Custom invent law."
    assert "no_prompt_dump" in pack


def test_cannot_clear_default_without_override() -> None:
    with pytest.raises(ValueError, match="override_defaults"):
        merge_rules(request_rules={"no_prompt_dump": ""})


def test_freeze_sets_ruleset_id() -> None:
    s = ClientSettings(rules={"coupon_presented": "Honor coupon codes from tools only."})
    pack, rid = freeze_session_rules(s)
    assert "coupon_presented" in pack
    assert rid.startswith("rules:")


def test_append_only_mid_session() -> None:
    frozen = merge_rules()
    out = append_session_rules(frozen, {"extra": "new rule"})
    assert out["extra"] == "new rule"
    with pytest.raises(ValueError, match="frozen"):
        append_session_rules(out, {"extra": "changed"})


def test_merge_rules_frozen_blocks_existing() -> None:
    merged = merge_rules_frozen(
        {"a": "keep", "b": "old"},
        {"b": "attack", "c": "new"},
        frozen=True,
    )
    assert merged == {"a": "keep", "b": "old", "c": "new"}


def test_output_request_requires_description() -> None:
    with pytest.raises(ValueError, match="description"):
        validate_output_request({"app": {"fields": {"x": {"type": "string"}}}})


def test_company_context_hard_truncate() -> None:
    words = " ".join(f"w{i}" for i in range(300))
    text, warns = truncate_company_context(words)
    assert len(text.split()) == 250
    assert any("hard" in w for w in warns)


def test_prepare_settings_merges() -> None:
    s = prepare_settings(
        {
            "company_context": "We sell beer.",
            "rules": {"loyalty": "Apply loyalty discounts from tools."},
            "output_request": {
                "app": {"fields": {"code": {"type": "string", "description": "code"}}},
            },
            "locale": "en-US",
        }
    )
    assert s.ruleset_id
    assert "loyalty" in (s.rules or {})
    assert "no_prompt_dump" in (s.rules or {})
    assert s.locale == "en-US"
    assert s.ai_process_result is False
    assert s.ignore_user_tool_path_hints is True


def test_ai_process_result_package_default_false() -> None:
    assert ClientSettings().ai_process_result is False
