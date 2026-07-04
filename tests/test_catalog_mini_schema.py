"""Mini-schema introspection and injection tests."""
import json

import pytest
from zeus_client.contract_hash import compute_contract_hash
from zeus_client.zeus.catalog import (
    _system_prompt_text,
    apply_injected_business_logic,
    get_mini_schema,
    getMiniSchema,
    inject_business_logic,
    render_injected_business_logic,
)
from tests.fixtures.catalog_brief import base_chat_req


def test_get_mini_schema_structure():
    s = get_mini_schema(base_chat_req(), values=False)
    assert s["scope"] == "beer-sample/_default"
    assert s["mode"] == "auto"
    assert set(s["entity_types"]) == {"Beer", "Brewery"}
    beer = s["entity_types"]["Beer"]
    assert beer["field_count"] == 8
    assert beer["fields"]["abv"] == {"kind": "number", "indexed": "gsi", "filterable": True}
    assert beer["fields"]["category"]["filterable"] is False
    assert beer["fields"]["brewery_id"]["fk_to"] == "Brewery"
    assert "examples" not in beer["fields"]["brewery_id"]
    brew = s["entity_types"]["Brewery"]
    assert brew["inverse_fks"] == [
        {"from_entity": "Beer", "from_path": "brewery_id", "kind": "entity_fk"}
    ]


def test_get_mini_schema_values():
    s = get_mini_schema(base_chat_req(), values=True)
    assert s["entity_types"]["Beer"]["fields"]["brewery_id"]["examples"] == ["coopers_brewery"]
    assert getMiniSchema(base_chat_req(), values=True) == s


def test_get_mini_schema_no_brief_is_empty():
    s = get_mini_schema({"messages": [{"role": "system", "content": "no brief here"}]})
    assert s == {"scope": "", "mode": "", "entity_types": {}}


def test_inject_validates_against_schema():
    cr = base_chat_req()
    cr2 = inject_business_logic(cr, {
        "entity_type": "Beer", "fields": ["abv"],
        "rule": "Do not process beers from California with abv > 7%.",
    })
    bl = cr2["guidance"]["injections"]["business_logic"]
    assert len(bl) == 1 and bl[0]["entity_type"] == "Beer"
    assert cr["guidance"]["injections"]["business_logic"] == []
    with pytest.raises(ValueError, match="Wine"):
        inject_business_logic(cr, {"entity_type": "Wine", "rule": "x"})
    with pytest.raises(ValueError, match="color"):
        inject_business_logic(cr, {"entity_type": "Beer", "fields": ["color"], "rule": "x"})
    cr3 = inject_business_logic(cr, "Be concise.")
    assert cr3["guidance"]["injections"]["business_logic"][0] == {"rule": "Be concise.", "id": "r1"}


def test_apply_is_hash_stable():
    cr = inject_business_logic(base_chat_req(), {
        "entity_type": "Beer", "fields": ["abv"],
        "rule": "Do not process beers from California with abv > 7%.",
    })
    before = compute_contract_hash(cr)
    applied = apply_injected_business_logic(cr)
    after = compute_contract_hash(applied)
    assert "Additional Business Rules" in applied["messages"][0]["content"]
    assert before == after


def test_render_section():
    cr = inject_business_logic(base_chat_req(), "Stay on topic.")
    section = render_injected_business_logic(cr)
    assert section.startswith("## Additional Business Rules (injected by middle-man)")
    assert "- (r1) Stay on topic." in section
    assert render_injected_business_logic(base_chat_req()) == ""


def test_get_mini_schema_from_path(tmp_path):
    path = tmp_path / "chat.json"
    path.write_text(json.dumps(base_chat_req()), encoding="utf-8")
    s = get_mini_schema(str(path), values=False)
    assert "Beer" in s["entity_types"]


def test_system_prompt_text_non_dict_instructions_unchanged():
    cr = {
        "messages": [{"role": "system", "content": "plain"}],
        "instructions": "not-a-dict",
    }
    assert _system_prompt_text(cr) == "plain"


def test_system_prompt_text_prefers_instructions_when_messages_plain():
    cr = {
        "messages": [{"role": "system", "content": "operator rules"}],
        "instructions": {"system_prompt": base_chat_req()["messages"][0]["content"]},
    }
    text = _system_prompt_text(cr)
    assert "## MINI-SCHEMA" in text


def test_get_mini_schema_messages_without_brief_use_instructions():
    cr = {
        "messages": [{"role": "system", "content": "plain rules only"}],
        "instructions": {"system_prompt": base_chat_req()["messages"][0]["content"]},
    }
    s = get_mini_schema(cr)
    assert "Beer" in s["entity_types"]


def test_get_mini_schema_reads_instructions_when_messages_empty():
    cr = {
        "messages": [],
        "instructions": {"system_prompt": base_chat_req()["messages"][0]["content"]},
    }
    s = get_mini_schema(cr)
    assert s["scope"] == "beer-sample/_default"


def test_get_mini_schema_reads_instructions_fallback():
    cr = {
        "messages": [{"role": "system", "content": "no brief"}],
        "instructions": {"system_prompt": base_chat_req()["messages"][0]["content"]},
    }
    s = get_mini_schema(cr)
    assert s["scope"] == "beer-sample/_default"


def test_get_mini_schema_bad_messages_structure():
    s = get_mini_schema({"messages": "not-a-list"})
    assert s == {"scope": "", "mode": "", "entity_types": {}}


def test_inject_rejects_invalid_rule_type():
    with pytest.raises(TypeError, match="must be str or dict"):
        inject_business_logic(base_chat_req(), 123, validate=False)


def test_validate_skipped_when_no_entity_type():
    cr = inject_business_logic(base_chat_req(), {"rule": "free text only"}, validate=True)
    assert cr["guidance"]["injections"]["business_logic"][0]["rule"] == "free text only"


def test_render_dict_rule_with_entity_type():
    cr = inject_business_logic(
        base_chat_req(),
        {"entity_type": "Beer", "rule": "Skip high abv."},
        validate=False,
    )
    section = render_injected_business_logic(cr)
    assert "[Beer]" in section


def test_apply_without_brief_marker_returns_unchanged():
    cr = inject_business_logic({"messages": [{"role": "system", "content": "plain"}]}, "rule", validate=False)
    out = apply_injected_business_logic(cr)
    assert out["messages"][0]["content"] == "plain"
    assert "Additional Business Rules" not in out["messages"][0]["content"]


def test_apply_skips_when_heading_already_present():
    cr = base_chat_req()
    cr = inject_business_logic(cr, "Already there.", validate=False)
    cr["messages"][0]["content"] += "\n\n## Additional Business Rules (injected by middle-man)\n- old"
    out = apply_injected_business_logic(cr)
    assert out["messages"][0]["content"].count("Additional Business Rules") == 1


def test_get_mini_schema_field_via_and_note():
    brief = """
## SCOPE BRIEF
scope: demo/_default
mode: auto

## MINI-SCHEMA
### Widget (fields: 2)
  - link_id  entity_fk  [gsi]  via=Other
  - status   display    [none]  -- note here
"""
    s = get_mini_schema({"messages": [{"role": "system", "content": brief}]})
    assert s["entity_types"]["Widget"]["fields"]["link_id"]["via"] == "Other"
    assert s["entity_types"]["Widget"]["fields"]["status"]["note"] == "note here"


def test_render_string_rule_branch():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = ["plain string rule"]
    section = render_injected_business_logic(cr)
    assert "- (r1) plain string rule" in section


def test_render_dict_rule_without_entity_type():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [{"id": "custom", "rule": "do thing"}]
    section = render_injected_business_logic(cr)
    assert "- (custom) do thing" in section
    assert "[" not in section.split("do thing")[0].split("- (custom)")[-1]


def test_render_mixed_string_and_dict_rules():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        "string rule",
        {"entity_type": "Beer", "id": "b1", "rule": "filter"},
        {"id": "plain", "rule": "no entity"},
    ]
    section = render_injected_business_logic(cr)
    assert "- (r1) string rule" in section
    assert "- (b1) [Beer] filter" in section
    assert "- (plain) no entity" in section


def test_render_skips_unsupported_rule_types():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [123, {"rule": "ok"}]
    section = render_injected_business_logic(cr)
    assert "- (r2) ok" in section
    assert "123" not in section


def test_render_dict_uses_text_field_and_json_fallback():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {"text": "from text key"},
        {"entity_type": "Beer", "extra": 1},
    ]
    section = render_injected_business_logic(cr)
    assert "- (r1) from text key" in section
    assert "[Beer]" in section
    assert "extra" in section


def test_render_dict_entity_type_empty_string_omits_brackets():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {"entity_type": "", "rule": "empty et"},
        {"entity_type": "Beer", "rule": "with et"},
    ]
    section = render_injected_business_logic(cr)
    assert "- (r1) empty et" in section
    assert "- (r2) [Beer] with et" in section


def test_apply_no_rules_returns_original():
    assert apply_injected_business_logic(base_chat_req()) == base_chat_req()


def test_apply_without_messages_only_instructions():
    cr = inject_business_logic(
        {"instructions": {"system_prompt": "rules\n## SCOPE BRIEF\nbrief"}},
        "rule text",
        validate=False,
    )
    out = apply_injected_business_logic(cr)
    assert "rule text" in out["instructions"]["system_prompt"]


def test_merge_scope_brief_skips_instr_when_mini_schema_in_sp():
    from zeus_client.zeus.catalog import merge_scope_brief

    base = {
        "messages": [{"content": "BASE"}],
        "instructions": {"system_prompt": "SYS\n## MINI-SCHEMA\nexisting"},
    }
    out = merge_scope_brief(base, "extra brief text")
    assert out["instructions"]["system_prompt"] == base["instructions"]["system_prompt"]


def test_get_mini_schema_inverse_fk_block():
    brief = """
## SCOPE BRIEF
scope: demo/_default
mode: auto

## MINI-SCHEMA
### Parent (fields: 0)
inverse_fks:
  not-a-valid-inverse-line
  \u2190 Child.parent_id  (entity_fk)  -- walk children
"""
    s = get_mini_schema({"messages": [{"role": "system", "content": brief}]})
    assert s["entity_types"]["Parent"]["inverse_fks"] == [
        {"from_entity": "Child", "from_path": "parent_id", "kind": "entity_fk"},
    ]


def test_merge_scope_brief_skips_instr_when_markers_present():
    from zeus_client.zeus.catalog import merge_scope_brief
    from tests.fixtures.catalog_brief import BRIEF

    base = {
        "messages": [{"content": "BASE"}],
        "instructions": {"system_prompt": f"SYS\n{BRIEF}"},
    }
    out = merge_scope_brief(base, "extra")
    assert out["instructions"]["system_prompt"].count("## SCOPE BRIEF") == 1


def test_apply_splices_instructions_system_prompt():
    cr = inject_business_logic(
        {
            "messages": [{"role": "system", "content": "x"}],
            "instructions": {"system_prompt": "rules\n## SCOPE BRIEF\nbrief"},
        },
        "Use find first.",
        validate=False,
    )
    out = apply_injected_business_logic(cr)
    assert "Use find first." in out["instructions"]["system_prompt"]