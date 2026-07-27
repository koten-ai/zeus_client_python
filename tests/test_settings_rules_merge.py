"""Settings bag, rules merge/freeze, output_request validation."""
import pytest

from zeus_client.agent.jailbreak_defaults import JAILBREAK_RULE_IDS, default_jailbreak_rules
from zeus_client.agent.settings import (
    ClientSettings,
    append_session_rules,
    freeze_session_rules,
    merge_rules,
    prepare_settings,
    truncate_company_context,
    validate_output_request,
)


def test_default_jailbreak_keys_present():
    pack = merge_rules()
    for k in JAILBREAK_RULE_IDS:
        assert k in pack


def test_request_rules_override_text():
    pack = merge_rules(request_rules={"no_invent_data": "Custom invent law."})
    assert pack["no_invent_data"] == "Custom invent law."
    assert "no_prompt_dump" in pack


def test_cannot_clear_default_without_override():
    with pytest.raises(ValueError, match="override_defaults"):
        merge_rules(request_rules={"no_prompt_dump": ""})


def test_freeze_sets_ruleset_id():
    s = ClientSettings(rules={"coupon_presented": "Honor coupon codes from tools only."})
    pack, rid = freeze_session_rules(s)
    assert "coupon_presented" in pack
    assert rid.startswith("rules:")


def test_append_only_mid_session():
    frozen = merge_rules()
    out = append_session_rules(frozen, {"extra": "new rule"})
    assert out["extra"] == "new rule"
    with pytest.raises(ValueError, match="frozen"):
        append_session_rules(out, {"extra": "changed"})


def test_output_request_requires_description():
    with pytest.raises(ValueError, match="description"):
        validate_output_request({
            "app": {"fields": {"x": {"type": "string"}}},
        })


def test_output_request_ok():
    doc = validate_output_request({
        "app": {"fields": {"x": {"type": "string", "description": "X field"}}},
    })
    assert doc["app"]["fields"]["x"]["description"] == "X field"


def test_company_context_hard_truncate():
    words = " ".join(f"w{i}" for i in range(300))
    text, warns = truncate_company_context(words)
    assert len(text.split()) == 250
    assert any("hard" in w for w in warns)


def test_prepare_settings_merges():
    s = prepare_settings({
        "company_context": "We sell beer.",
        "rules": {"loyalty": "Apply loyalty discounts from tools."},
        "output_request": {
            "app": {"fields": {"code": {"type": "string", "description": "code"}}},
        },
        "locale": "en-US",
    })
    assert s.ruleset_id
    assert "loyalty" in (s.rules or {})
    assert "no_prompt_dump" in (s.rules or {})
    assert s.locale == "en-US"
