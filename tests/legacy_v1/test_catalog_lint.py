"""ZC-35: conflict linter for open chat_request rules."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from tests.fixtures.catalog_brief import base_chat_req
from zeus_client.contract_hash import (
    HASH_EXCLUDED_ROOTS,
    LOCKED_POINTERS,
    compute_contract_hash,
)
from zeus_client.zeus.lint import (
    Finding,
    inventory_open_rules,
    score_findings,
)

from zeus_client import ConflictReport, hash_policy_summary, lint_chat_request

FIXTURE = Path(__file__).parent / "fixtures" / "lint_conflict_chat_request.json"
BUNDLED_ANALYTICS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "data"
    / "chat_requests"
    / "chat_request_analytics_v2.json"
)


def _conflict_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_hash_policy_constants_documented():
    policy = hash_policy_summary()
    assert "guidance" in policy["hash_excluded_roots"]
    assert any(p.startswith("/instructions") for p in policy["locked_pointers"])
    assert HASH_EXCLUDED_ROOTS[0] == "guidance"
    assert "/verbs" in LOCKED_POINTERS


def test_inventory_open_rules_from_fixture():
    atoms = inventory_open_rules(_conflict_fixture())
    kinds = {a.kind for a in atoms}
    assert "business_logic" in kinds
    assert "optimal_path" in kinds
    assert len([a for a in atoms if a.kind == "business_logic"]) >= 5


def test_lint_conflict_fixture_flags_high_severity():
    report = lint_chat_request(_conflict_fixture())
    assert isinstance(report, ConflictReport)
    assert report.finding_count >= 3
    assert report.conflict_score > 0
    assert report.severity in ("low", "medium", "high")
    check_ids = {f.check_id for f in report.findings}
    assert "negation_pair" in check_ids
    assert "structured_predicate_clash" in check_ids
    # Schema orphan Wine
    assert "schema_unknown_entity" in check_ids
    # Structural pipeline issues
    assert "optimal_path_unknown_verb" in check_ids or "optimal_path_missing_as" in check_ids
    assert "locked" in report.locked_paths_note.lower()
    assert (
        "never rewritten" in report.locked_paths_note.lower()
        or "not rewritten" in report.locked_paths_note.lower()
    )


def test_lint_does_not_mutate_input():
    doc = _conflict_fixture()
    before = deepcopy(doc)
    h_before = compute_contract_hash(doc)
    _ = lint_chat_request(doc)
    assert doc == before
    assert compute_contract_hash(doc) == h_before


def test_lint_clean_base_chat_req_is_clean():
    cr = base_chat_req()
    report = lint_chat_request(cr)
    assert report.finding_count == 0
    assert report.conflict_score == 0
    assert report.severity == "none"


def test_lint_bundled_analytics_no_high_open_conflicts():
    """Bundled catalogs should not have high-severity open-rule conflicts."""
    if not BUNDLED_ANALYTICS.is_file():
        pytest.skip("bundled analytics catalog missing")
    doc = json.loads(BUNDLED_ANALYTICS.read_text(encoding="utf-8"))
    report = lint_chat_request(doc)
    high = [f for f in report.findings if f.severity == "high"]
    assert not high, f"unexpected high findings: {high}"


def test_negation_pair_always_never_find():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {"id": "a", "rule": "Always prefer find for Brewery lookups."},
        {"id": "b", "rule": "Never use find for Brewery queries."},
    ]
    report = lint_chat_request(cr, include_structural=False, include_schema=False)
    assert any(f.check_id == "negation_pair" for f in report.findings)
    assert report.severity in ("medium", "high")


def test_structured_predicate_clash_deny_require():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {
            "id": "d",
            "entity_type": "Beer",
            "fields": ["abv"],
            "rule": "deny high abv",
            "deny_when": {"abv": {">": 7}},
        },
        {
            "id": "r",
            "entity_type": "Beer",
            "fields": ["abv"],
            "rule": "require higher abv",
            "require": {"abv": {">=": 8}},
        },
    ]
    report = lint_chat_request(cr, include_structural=False)
    assert any(f.check_id == "structured_predicate_clash" for f in report.findings)


def test_duplicate_rule_text():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {"id": "r1", "rule": "Stay on topic always."},
        {"id": "r2", "rule": "Stay on topic always."},
    ]
    report = lint_chat_request(cr, include_structural=False, include_schema=False)
    assert any(f.check_id == "duplicate_rule_text" for f in report.findings)


def test_optimal_path_unknown_verb_and_return():
    cr = base_chat_req()
    cr["verbs"] = [
        {
            "function": {"name": "find", "parameters": {"type": "object", "properties": {}}},
            "type": "function",
        },
        {
            "function": {"name": "return", "parameters": {"type": "object", "properties": {}}},
            "type": "function",
        },
    ]
    cr["guidance"]["optimal_paths"] = [
        {
            "when_to_use": "broken",
            "pipeline": [{"verb": "teleport", "params": {}}],
            "return": ["find"],
        }
    ]
    report = lint_chat_request(cr, include_schema=False)
    ids = {f.check_id for f in report.findings}
    assert "optimal_path_unknown_verb" in ids
    assert "optimal_path_missing_as" in ids
    assert "optimal_path_return_is_verb" in ids


def test_score_findings_bands():
    assert score_findings([]) == (0, "none")
    low = [Finding("x", "low", "m", "p")]
    assert score_findings(low)[1] == "low"
    med = [
        Finding("x", "medium", "m", "p"),
        Finding("y", "medium", "m", "p"),
        Finding("z", "medium", "m", "p"),
    ]
    score, band = score_findings(med)
    assert score == 30
    assert band == "medium"
    high = [Finding("x", "high", "m", "p"), Finding("y", "high", "m", "p")]
    score, band = score_findings(high)
    assert score == 50
    assert band == "high"


def test_report_to_dict_and_text():
    report = lint_chat_request(_conflict_fixture())
    d = report.to_dict()
    assert d["finding_count"] == report.finding_count
    assert "findings" in d
    text = report.format_text()
    assert "conflict lint" in text
    assert report.summary_line().startswith("catalog_lint:")


def test_cli_module_main_on_fixture(capsys):
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "lint_chat_request.py"
    spec = importlib.util.spec_from_file_location("lint_chat_request_cli", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    rc = mod.main([str(FIXTURE)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "catalog_lint" in out or "conflict lint" in out

    rc_fail = mod.main([str(FIXTURE), "--fail-on", "low"])
    assert rc_fail == 1
    capsys.readouterr()  # discard text report from fail-on run

    rc_json = mod.main([str(FIXTURE), "--json"])
    assert rc_json == 0
    payload = json.loads(capsys.readouterr().out)
    assert "conflict_score" in payload
