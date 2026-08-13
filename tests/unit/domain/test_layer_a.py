"""Layer A parse / peel / G-split oracles (ZCP-17)."""

from __future__ import annotations

from zeus_client.domain.layer_a import (
    artifacts_view,
    normalize_triggers,
    parse_layer_a,
    peel_layer_a_summary,
    ui_view,
    user_facing_answer,
    validate_app_output,
)


def _valid_return(**extra):
    base = {
        "summary": "Found two beers.",
        "query_decomposition": {"intent": "List", "entity": "Beer"},
        "decomposition": {"targets": [{"entity_type": "Beer"}], "predicates": {}},
        "confidence": "high",
    }
    base.update(extra)
    return base


def test_required_four_ok():
    layer = parse_layer_a(_valid_return())
    assert layer.ok
    assert layer.summary.startswith("Found")
    assert layer.confidence == "high"


def test_missing_summary_errors():
    layer = parse_layer_a(
        {
            "query_decomposition": {},
            "decomposition": {},
            "confidence": "med",
        }
    )
    assert not layer.ok
    assert any("summary" in e for e in layer.errors)


def test_qd_must_be_object():
    layer = parse_layer_a(_valid_return(query_decomposition="list beers"))
    assert not layer.ok
    assert any("query_decomposition" in e for e in layer.errors)


def test_object_triggers():
    layer = parse_layer_a(
        _valid_return(
            business_rules_triggers={"no_invent_data": True, "coupon": False},
        )
    )
    assert layer.business_rules_triggers["no_invent_data"] is True
    assert layer.business_rules_triggers["coupon"] is False


def test_array_triggers_dual_read():
    trig, warns = normalize_triggers(
        [True, False, True],
        rule_ids=["a", "b", "c"],
        allow_array=True,
    )
    assert trig == {"a": True, "b": False, "c": True}
    assert any("dual-read" in w for w in warns)


def test_array_triggers_rejected_when_disabled():
    trig, warns = normalize_triggers([True], rule_ids=["a"], allow_array=False)
    assert trig == {}
    assert any("rejected" in w for w in warns)


def test_ui_view_strips_g2():
    layer = parse_layer_a(
        _valid_return(
            jail_break_attempt=0.9,
            wish_i_knew=[{"gap": "x"}],
            business_rules_triggers={"no_prompt_dump": True},
        )
    )
    ui = ui_view(layer)
    assert "wish_i_knew" not in ui
    assert "jail_break_attempt" not in ui
    assert "business_rules_triggers" not in ui
    assert ui["summary"] == layer.summary


def test_artifacts_keep_g2_and_dual_score():
    layer = parse_layer_a(_valid_return(jail_break_attempt=0.4))
    art = artifacts_view(layer, hooks_jailbreak_score=0.9, policy="answer")
    assert art["jail_break_attempt"] == 0.4
    assert art["hooks_jailbreak_score"] == 0.9
    assert art["policy"] == "answer"


def test_app_output_type_check_strip():
    fields = {"offer_code": {"type": "string", "description": "promo"}}
    out, errs = validate_app_output(
        {"offer_code": 123},
        fields,
        on_error="strip",
    )
    assert out == {}
    assert errs


def test_app_output_ok():
    fields = {"offer_code": {"type": "string", "description": "promo"}}
    out, errs = validate_app_output(
        {"offer_code": "SAVE10"},
        fields,
        on_error="strip",
    )
    assert out == {"offer_code": "SAVE10"}
    assert not errs


def test_parse_app_output_with_output_request():
    layer = parse_layer_a(
        _valid_return(app_output={"offer_code": "X"}),
        output_request={
            "app": {
                "fields": {"offer_code": {"type": "string", "description": "code"}}
            },
        },
    )
    assert layer.app_output == {"offer_code": "X"}


def test_peel_layer_a_summary_fenced_yaml_dump():
    dump = (
        "```\n"
        'summary: "Found two great salons in Tampa."\n'
        "confidence: med\n"
        'query_decomposition: {"intent": "salons"}\n'
        'decomposition: {"targets": []}\n'
        "policy_action: answer\n"
        "wish_i_knew: []\n"
        "```"
    )
    assert peel_layer_a_summary(dump) == "Found two great salons in Tampa."
    assert user_facing_answer(dump) == "Found two great salons in Tampa."
    assert user_facing_answer(dump, ui_text="UI preferred") == "UI preferred"
    # G2 never surfaces via peel path
    assert "wish_i_knew" not in user_facing_answer(dump)


def test_user_facing_answer_passes_prose():
    prose = "Here are three salons worth visiting."
    assert peel_layer_a_summary(prose) is None
    assert user_facing_answer(prose) == prose


def test_peel_layer_a_summary_unescapes_newlines():
    dump = (
        'summary: "Line one.\\nLine two."\n'
        "confidence: high\n"
        "policy_action: answer\n"
        'query_decomposition: {"intent": "x"}\n'
    )
    assert peel_layer_a_summary(dump) == "Line one.\nLine two."
