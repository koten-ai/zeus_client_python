"""Post-terminate policy table oracles (ZCP-17)."""

from __future__ import annotations

from zeus_client_v2.config.models import ClientSettings
from zeus_client_v2.domain.layer_a import parse_layer_a
from zeus_client_v2.domain.policy import decide_policy, sticky_or_flags


def _layer(**extra):
    base = {
        "summary": "Here are results.",
        "query_decomposition": {"intent": "List", "entity": "Beer"},
        "decomposition": {"targets": [{"entity_type": "Beer"}]},
        "confidence": "high",
    }
    base.update(extra)
    return parse_layer_a(base)


def test_default_answer_policy():
    d = decide_policy(_layer(policy_action="answer"))
    assert d.policy == "answer"
    assert d.ui_text == "Here are results."


def test_hooks_must_refuse():
    d = decide_policy(_layer(), hooks_must_refuse=True)
    assert d.policy == "refuse"
    assert d.forced
    # refuse chrome is soft default — not G2 dumps
    assert "wish_i_knew" not in d.ui_text
    assert "jail_break" not in d.ui_text.lower()


def test_jailbreak_triggers_and_score():
    layer = _layer(
        business_rules_triggers={"no_prompt_dump": True},
        jail_break_attempt=0.8,
    )
    d = decide_policy(layer, hooks_jailbreak_score=0.1)
    assert d.policy == "refuse"
    assert d.hooks_jailbreak_score == 0.1
    assert layer.jail_break_attempt == 0.8
    art = d.artifacts(layer)
    assert art["jail_break_attempt"] == 0.8
    assert art["hooks_jailbreak_score"] == 0.1
    assert "wish_i_knew" in art  # G2 in artifacts OK
    ui = d.ui(layer)
    assert "wish_i_knew" not in ui
    assert "jail_break_attempt" not in ui


def test_model_policy_action_clarify():
    d = decide_policy(_layer(policy_action="clarify", summary="Which city?"))
    assert d.policy == "clarify"
    assert d.ui_text == "Which city?"


def test_sticky_or_flags():
    flags = sticky_or_flags({"a": True}, {"a": False, "b": True})
    assert flags == {"a": True, "b": True}


def test_soft_require_policy_action():
    s = ClientSettings(soft_require_policy_action=True)
    d = decide_policy(_layer(), settings=s, brand_inject_present=True)
    assert d.soft_require_policy_action_missing is True


def test_layer_a_validation_failed_forces_error():
    bad = parse_layer_a({"confidence": "high"})  # missing required four
    d = decide_policy(bad)
    assert d.policy == "error"
    assert d.forced
    assert d.reason == "layer_a_validation_failed"


def test_sticky_flags_from_settings():
    s = ClientSettings(sticky_flags={"loyalty": True})
    layer = _layer(business_rules_triggers={"promo": True})
    d = decide_policy(layer, settings=s)
    assert d.flags == {"loyalty": True, "promo": True}
