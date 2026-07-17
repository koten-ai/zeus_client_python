"""ZC-36: structured hard conflicts, open-vs-locked, cache, config."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from zeus_client import (
    CatalogLintConfig,
    clear_lint_cache,
    lint_catalog_assembled,
    lint_chat_request,
    resolve_lint_config,
    structured_rule_schema,
)
from zeus_client.zeus.lint import (
    catalog_lint_cache_key,
    extract_locked_tool_stances,
    inventory_open_rules,
    structured_open_rules,
)
from tests.fixtures.catalog_brief import base_chat_req

FIXTURES = Path(__file__).parent / "fixtures"
HARD_FIXTURE = FIXTURES / "lint_hard_effect_chat_request.json"
OVL_FIXTURE = FIXTURES / "lint_open_vs_locked_chat_request.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_lint_cache()
    yield
    clear_lint_cache()


def test_structured_rule_schema_documents_effects():
    schema = structured_rule_schema()
    assert "prefer_tool" in schema["fields"]["effect"]
    assert "forbid_tool" in schema["fields"]["effect"]
    assert schema["examples"]


def test_inventory_parses_structured_effects():
    doc = _load(HARD_FIXTURE)
    atoms = inventory_open_rules(doc)
    structured = structured_open_rules(atoms)
    assert len(structured) == 2
    effects = {a.effect for a in structured}
    assert effects == {"prefer_tool", "forbid_tool"}
    assert all(a.tool == "find" for a in structured)
    assert all(a.provenance and a.provenance.get("id") for a in structured)


def test_hard_effect_conflict_fixture():
    report = lint_chat_request(
        _load(HARD_FIXTURE),
        soft_nl=False,
        open_vs_locked=False,
    )
    assert report.lint_version == "v2"
    assert report.hard_finding_count >= 1
    assert any(f.check_id == "hard_effect_conflict" for f in report.findings)
    hard = report.hard_findings()
    assert hard
    assert hard[0].layer == "hard"
    assert hard[0].confidence == "high"
    assert {hard[0].rule_id_a, hard[0].rule_id_b} == {
        "prefer-find-beer",
        "ban-find-beer",
    }


def test_hard_effect_when_mismatch_no_conflict():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {
            "id": "prefer-beer",
            "effect": "prefer_tool",
            "tool": "find",
            "when": {"entity_type": "Beer"},
        },
        {
            "id": "forbid-brewery",
            "effect": "forbid_tool",
            "tool": "find",
            "when": {"entity_type": "Brewery"},
        },
    ]
    report = lint_chat_request(cr, soft_nl=False, open_vs_locked=False, include_schema=False)
    assert not any(f.check_id == "hard_effect_conflict" for f in report.findings)


def test_open_vs_locked_fixture():
    report = lint_chat_request(
        _load(OVL_FIXTURE),
        soft_nl=False,
        hard_conflicts=True,
        open_vs_locked=True,
    )
    assert report.open_vs_locked_count >= 1
    assert any(
        f.check_id == "open_vs_locked_forbid_vs_prefer" for f in report.findings
    )
    assert report.open_vs_locked_findings()[0].layer == "open_vs_locked"


def test_extract_locked_tool_stances():
    stances = extract_locked_tool_stances(_load(OVL_FIXTURE))
    assert "find" in stances["prefer"]


def test_soft_nl_can_be_disabled():
    cr = base_chat_req()
    cr["guidance"]["injections"]["business_logic"] = [
        {"id": "a", "rule": "Always prefer find for Brewery lookups."},
        {"id": "b", "rule": "Never use find for Brewery queries."},
    ]
    with_soft = lint_chat_request(cr, soft_nl=True, hard_conflicts=False, open_vs_locked=False, include_schema=False)
    without = lint_chat_request(cr, soft_nl=False, hard_conflicts=False, open_vs_locked=False, include_schema=False)
    assert any(f.check_id == "negation_pair" for f in with_soft.findings)
    assert with_soft.soft_finding_count >= 1
    assert without.finding_count == 0


def test_mode_off_via_assembled():
    doc = _load(HARD_FIXTURE)
    cfg = CatalogLintConfig(mode="off")
    report = lint_catalog_assembled(doc, config=cfg)
    assert report.finding_count == 0
    assert report.mode == "off"


def test_assemble_cache_hit_and_invalidation():
    doc = _load(HARD_FIXTURE)
    cfg = resolve_lint_config(doc, overrides={"mode": "assemble", "soft_nl": False})
    r1 = lint_catalog_assembled(doc, config=cfg, use_cache=True)
    assert r1.from_cache is False
    assert r1.hard_finding_count >= 1
    r2 = lint_catalog_assembled(doc, config=cfg, use_cache=True)
    assert r2.from_cache is True
    assert r2.hard_finding_count == r1.hard_finding_count
    # Mutate open rules → new cache key
    doc2 = deepcopy(doc)
    doc2["guidance"]["injections"]["business_logic"].append(
        {
            "id": "extra",
            "effect": "prefer_tool",
            "tool": "search",
            "when": {"entity_type": "Beer"},
        }
    )
    assert catalog_lint_cache_key(doc, config=cfg) != catalog_lint_cache_key(doc2, config=cfg)
    r3 = lint_catalog_assembled(doc2, config=cfg, use_cache=True)
    assert r3.from_cache is False


def test_meets_fail_on_hard():
    report = lint_chat_request(_load(HARD_FIXTURE), soft_nl=False, open_vs_locked=False)
    assert report.meets_fail_on("hard") is True
    assert report.meets_fail_on("none") is False
    clean = lint_chat_request(base_chat_req(), soft_nl=False, open_vs_locked=False)
    assert clean.meets_fail_on("hard") is False


def test_resolve_lint_config_from_guidance_and_debug(monkeypatch):
    monkeypatch.delenv("ZEUS_CATALOG_LINT_MODE", raising=False)
    cr = base_chat_req()
    cr["guidance"]["debug"] = True
    cfg = resolve_lint_config(cr)
    assert cfg.mode == "debug"

    cr2 = base_chat_req()
    cr2["guidance"]["catalog_lint"] = {"mode": "ci", "fail_on": "hard", "soft_nl": False}
    cfg2 = resolve_lint_config(cr2)
    assert cfg2.mode == "ci"
    assert cfg2.fail_on == "hard"
    assert cfg2.soft_nl is False


def test_resolve_lint_config_env_override(monkeypatch):
    monkeypatch.setenv("ZEUS_CATALOG_LINT_MODE", "assemble")
    cr = base_chat_req()
    cfg = resolve_lint_config(cr)
    assert cfg.mode == "assemble"
    monkeypatch.delenv("ZEUS_CATALOG_LINT_MODE", raising=False)


def test_cli_fail_on_hard_and_schema(capsys):
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "lint_chat_request.py"
    spec = importlib.util.spec_from_file_location("lint_chat_request_cli_v2", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    rc_schema = mod.main(["--schema"])
    assert rc_schema == 0
    schema_out = json.loads(capsys.readouterr().out)
    assert "prefer_tool" in schema_out["fields"]["effect"]

    rc = mod.main([str(HARD_FIXTURE), "--fail-on", "hard", "--no-soft"])
    assert rc == 1
    capsys.readouterr()

    rc_ok = mod.main([str(HARD_FIXTURE), "--fail-on", "none", "--no-soft", "--json"])
    assert rc_ok == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hard_finding_count"] >= 1
    assert payload["lint_version"] == "v2"


def test_lint_does_not_mutate_hard_fixture():
    from zeus_client.contract_hash import compute_contract_hash

    doc = _load(HARD_FIXTURE)
    before = deepcopy(doc)
    h_before = compute_contract_hash(doc)
    _ = lint_chat_request(doc)
    assert doc == before
    assert compute_contract_hash(doc) == h_before
