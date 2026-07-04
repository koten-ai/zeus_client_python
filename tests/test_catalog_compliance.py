"""Business-rule compliance tests."""
import pytest

from zeus_client.zeus.catalog import (
    audit_rows_against_rules,
    inject_business_logic,
    render_injected_business_logic,
)


def base_chat_req():
    return {"messages": [{"role": "system", "content": "x"}]}


def test_rule_ids_assigned():
    cr = inject_business_logic(
        base_chat_req(), "Be concise.", {"rule": "No discount below zero."}, validate=False,
    )
    bl = cr["guidance"]["injections"]["business_logic"]
    assert [r["id"] for r in bl] == ["r1", "r2"]
    cr2 = inject_business_logic(cr, {"id": "loyalty", "rule": "10% off"}, validate=False)
    assert cr2["guidance"]["injections"]["business_logic"][2]["id"] == "loyalty"


def test_self_report_is_off_by_default():
    cr = inject_business_logic(base_chat_req(), "Be concise.", validate=False)
    section = render_injected_business_logic(cr)
    assert "(r1)" in section
    assert "rule_compliance" not in section


def test_self_report_opt_in():
    cr = inject_business_logic(base_chat_req(), "Be concise.", validate=False)
    cr["guidance"]["injections"]["report_compliance"] = True
    section = render_injected_business_logic(cr)
    assert "rule_compliance" in section
    assert "applied" in section and "not_triggered" in section


def test_debug_implies_self_report():
    cr = inject_business_logic(base_chat_req(), "Be concise.", validate=False)
    cr.setdefault("guidance", {})["debug"] = True
    section = render_injected_business_logic(cr)
    assert "rule_compliance" in section
    cr["guidance"]["injections"]["report_compliance"] = False
    assert "rule_compliance" not in render_injected_business_logic(cr)


def test_audit_detects_violation():
    cr = inject_business_logic(
        base_chat_req(),
        {
            "id": "r1",
            "rule": "Do not process California beers with abv > 7%.",
            "deny_when": {"state": "California", "abv": {">": 7}},
        },
        validate=False,
    )
    rules = cr["guidance"]["injections"]["business_logic"]
    rows = [
        {"name": "Hoppy", "state": "California", "abv": 8.2},
        {"name": "Light", "state": "California", "abv": 4.0},
        {"name": "Texan", "state": "Texas", "abv": 9.0},
        {"name": "NoAbv", "state": "California"},
    ]
    res = audit_rows_against_rules(rows, rules)
    assert len(res) == 1
    assert res[0]["status"] == "violation"
    assert [v["name"] for v in res[0]["violations"]] == ["Hoppy"]
    clean = [{"name": "Light", "state": "California", "abv": 4.0}]
    assert audit_rows_against_rules(clean, rules)[0]["status"] == "ok"


def test_audit_unverifiable_for_freetext():
    cr = inject_business_logic(base_chat_req(), "Be polite.", validate=False)
    res = audit_rows_against_rules([{"x": 1}], cr)
    assert res[0]["status"] == "unverifiable"


def test_audit_require_predicate():
    rules = [{"id": "r1", "rule": "every row must be approved", "require": {"status": "approved"}}]
    rows = [{"status": "approved"}, {"status": "pending"}]
    res = audit_rows_against_rules(rows, rules)
    assert res[0]["status"] == "violation"
    assert res[0]["violations"] == [{"status": "pending"}]


def test_audit_string_rule_entry():
    res = audit_rows_against_rules([{"x": 1}], ["Be polite."])
    assert res[0]["id"] == "r1"
    assert res[0]["status"] == "unverifiable"


def test_audit_unknown_predicate_op():
    rules = [{"rule": "bad op", "deny_when": {"abv": {"???": 7}}}]
    with pytest.raises(ValueError, match="unknown predicate op"):
        audit_rows_against_rules([{"abv": 8}], rules)


def test_audit_type_mismatch_clause_no_match():
    rules = [{"rule": "numeric compare", "deny_when": {"abv": {">": 7}}}]
    res = audit_rows_against_rules([{"abv": "not-a-number"}], rules)
    assert res[0]["status"] == "ok"