"""Offline conformance adapter tests (ZCP-21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conformance.paths import load_pins, resolve_design_root
from tests.conformance.run_suite import run_suite


def _require_design_root():
    """Conformance fixtures live in sibling zeus_client_design (pins local:../)."""
    try:
        design = resolve_design_root(load_pins())
    except FileNotFoundError as e:
        pytest.skip(str(e))
    if not (design / "conformance" / "manifest.json").is_file():
        pytest.skip(f"conformance manifest missing under {design}")
    return design


@pytest.mark.asyncio
async def test_conformance_suite_candidate_offline():
    """Required L0–L2 + detective min tapes green offline against design suite."""
    design = _require_design_root()
    assert (design / "conformance" / "manifest.json").is_file()

    report = await run_suite(
        levels={"L0", "L1", "L2", "L_detective", "L_rewind"},
        include_seed=False,
    )
    assert report["suite_version"] == "conformance-0.2-dev"
    assert report["language"] == "python"
    assert report["claim_level"] == "candidate"
    # schema-ish required keys
    for k in (
        "suite_version",
        "language",
        "package",
        "package_version",
        "client_floor",
        "started_at",
        "finished_at",
        "summary",
        "cases",
    ):
        assert k in report

    s = report["summary"]
    failed = [c for c in report["cases"] if c["status"] in ("failed", "error")]
    assert s["failed"] == 0 and s.get("error", 0) == 0, json.dumps(failed, indent=2)
    assert s["passed"] >= 10

    # Must cover plan minimum
    ids = {c["id"] for c in report["cases"] if c["status"] == "passed"}
    assert "L0.catalog.load_mock.001" in ids
    assert "L1.loop.single_tool_return.001" in ids
    assert "L2.layer_a.required_four.001" in ids
    assert "L2.policy.matrix.001" in ids
    assert any(i.startswith("DT.smooth_short") for i in ids)
    assert any(i.startswith("DT.fail_zeus") for i in ids)


def test_run_suite_cli_exit_zero():
    import subprocess
    import sys

    _require_design_root()
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run(
        [sys.executable, str(root / "tests" / "conformance" / "run_suite.py")],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    assert "passed=" in r.stdout
