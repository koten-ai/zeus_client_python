"""base-5 control plane (ZC-WISH-002…010, 014)."""
import pytest

from zeus_client.agent.control_plane import (
    DEFAULT_JAILBREAK_RULES,
    OutputRequestError,
    RuleMergeError,
    apply_policy_table,
    apply_policy_table_from_payload,
    freeze_rules,
    inject_control_plane_blocks,
    merge_rules,
    normalize_output_request_app_fields,
    render_output_request_block,
    ruleset_id,
    settings_from_mapping,
    truncate_company_context,
    validate_app_output,
)
from zeus_client.agent.layer_a import parse_layer_a
from zeus_client.agent.response import extract_structured_response
from zeus_client.zeus.catalog import (
    _base_id_from_filename,
    _mode_from_filename,
    chat_request_path,
    load_chat_request_file,
)


def test_default_jailbreak_keys_present():
    pack = merge_rules()
    for k in DEFAULT_JAILBREAK_RULES:
        assert k in pack
        assert pack[k]


def test_merge_rules_tenant_and_request_win():
    pack = merge_rules(
        {"coupon_presented": "If coupon, note it."},
        {"coupon_presented": "Request wins."},
    )
    assert pack["coupon_presented"] == "Request wins."
    assert "no_prompt_dump" in pack


def test_merge_rejects_blank_jailbreak_without_override():
    with pytest.raises(RuleMergeError):
        merge_rules({"no_prompt_dump": ""})


def test_merge_allows_blank_with_override_defaults():
    pack = merge_rules(
        {"no_prompt_dump": "custom only"},
        override_defaults=True,
        base={},
    )
    assert pack.get("no_prompt_dump") == "custom only"
    # no automatic restore when base={} and override_defaults
    assert "ignore_system" not in pack


def test_freeze_append_only():
    frozen = freeze_rules(
        {"a": "one"},
        append={"a": "rewrite ignored", "b": "two"},
    )
    assert frozen == {"a": "one", "b": "two"}


def test_ruleset_id_stable():
    a = ruleset_id({"x": "1", "y": "2"})
    b = ruleset_id({"y": "2", "x": "1"})
    assert a == b
    assert a.startswith("rs_")


def test_company_context_hard_truncate():
    words = " ".join(f"w{i}" for i in range(300))
    text, meta = truncate_company_context(words)
    assert meta["truncated"] is True
    assert meta["words"] == 250
    assert len(text.split()) == 250


def test_output_request_rejects_type_only():
    with pytest.raises(OutputRequestError):
        normalize_output_request_app_fields(
            {"fields": {"sum_favorites": "INT"}}
        )


def test_output_request_render_and_validate():
    oreq = {
        "app": {
            "fields": {
                "offer_code": {
                    "type": "string",
                    "description": "Promo code if presented, else empty",
                },
                "sum_favorites": {
                    "type": "integer",
                    "description": "Sum favorites; 0 if none",
                },
            }
        }
    }
    fields = normalize_output_request_app_fields(oreq)
    assert "offer_code" in fields
    block = render_output_request_block(oreq)
    assert "Promo code" in block
    assert "app_output" in block

    cleaned, errs = validate_app_output(
        {"offer_code": "SAVE10", "sum_favorites": "bad"},
        oreq,
    )
    assert cleaned == {"offer_code": "SAVE10"}
    assert any("sum_favorites" in e for e in errs)


def test_policy_table_refuse_on_hooks():
    bag = parse_layer_a(
        {
            "summary": "hack attempt",
            "query_decomposition": {"intent": "x", "entity": "y"},
            "decomposition": {"text": "z"},
            "confidence": "low",
            "policy_action": "answer",
            "jail_break_attempt": 0.9,
            "business_rules_triggers": {"ignore_system": True},
        }
    )
    pr = apply_policy_table(bag, hooks_jailbreak_score=0.1)
    assert pr.policy_action == "refuse"
    assert pr.model_jail_break_attempt == 0.9
    assert pr.hooks_jailbreak_score == 0.1  # dual scores kept


def test_policy_table_clarify_when_missing_required():
    pr = apply_policy_table_from_payload(
        {"summary": "hi", "policy_action": "answer"},
    )
    assert pr.policy_action == "clarify"
    assert not pr.layer_a.required_four_ok


def test_inject_control_plane_blocks():
    chat = {
        "messages": [
            {
                "role": "system",
                "content": "Base.\n\n## SCOPE BRIEF\n\nscope: beer/_default\n",
            }
        ]
    }
    rules = merge_rules({"coupon_presented": "Note coupons."})
    out = inject_control_plane_blocks(
        chat,
        rules=rules,
        company_context="Beer and Brewery are product entities.",
        output_request={
            "app": {
                "fields": {
                    "n": {"type": "integer", "description": "Count of rows"}
                }
            }
        },
    )
    content = out["messages"][0]["content"]
    assert "## Company context" in content
    assert "coupon_presented:" in content
    assert "## Output request" in content
    assert "## SCOPE BRIEF" in content
    # inject after brief
    assert content.index("## SCOPE BRIEF") < content.index("## Company context")


def test_mode_and_base_from_filename():
    assert _mode_from_filename("chat_request_analytics_base-5.3.json") == "analytics"
    assert _base_id_from_filename("chat_request_analytics_base-5.3.json") == "base-5.3"
    assert _mode_from_filename("chat_request_fraud_v2_min.json") == "fraud"
    assert _mode_from_filename("chat_request_code_v2.json") == "code"


def test_chat_request_path_base_id(tmp_path, monkeypatch):
    import zeus_client.zeus.catalog as cat

    d = tmp_path / "cats"
    d.mkdir()
    (d / "chat_request_analytics_base-5.3.json").write_text(
        '{"_lineage":{"base_id":"base-5.3","mode":"analytics"},"messages":[]}',
        encoding="utf-8",
    )
    (d / "chat_request_analytics_v2.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cat, "bundled_chat_requests_dir", lambda: d)
    monkeypatch.setattr(cat, "chat_request_search_dirs", lambda *a, **k: [d])

    p = chat_request_path("v2", "analytics", base_id="base-5.3")
    assert p is not None
    assert p.name == "chat_request_analytics_base-5.3.json"
    doc = load_chat_request_file(p, expect_base_id="base-5.3")
    assert doc["_lineage"]["base_id"] == "base-5.3"


def test_load_chat_request_file_mismatch(tmp_path):
    p = tmp_path / "chat_request_analytics_base-5.2.json"
    p.write_text(
        '{"_lineage":{"base_id":"base-5.2"},"messages":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mismatch"):
        load_chat_request_file(p, expect_base_id="base-5.3")


def test_extract_structured_response_with_policy():
    trace = {
        "steps": [
            {
                "type": "return",
                "args": {
                    "summary": "Listed beers",
                    "query_decomposition": {"intent": "list", "entity": "Beer"},
                    "decomposition": {"text": "ok"},
                    "confidence": "high",
                    "policy_action": "answer",
                    "app_output": {"n": 3},
                },
            }
        ]
    }
    resp = extract_structured_response(
        "",
        trace,
        {},
        apply_policy=True,
        output_request={
            "app": {
                "fields": {
                    "n": {"type": "integer", "description": "Count"}
                }
            }
        },
    )
    assert resp.policy is not None
    assert resp.policy.policy_action == "answer"
    assert resp.policy.app_output == {"n": 3}
    assert resp.answer == "Listed beers"
    assert resp.layer_a is not None


def test_settings_from_mapping():
    s = settings_from_mapping(
        {
            "max_rounds": 4,
            "locale": "en-US",
            "denied_verbs": ["analyze"],
            "output_request": {"app": {"fields": {}}},
        }
    )
    assert s.max_rounds == 4
    assert s.locale == "en-US"
    assert s.denied_verbs == ["analyze"]
