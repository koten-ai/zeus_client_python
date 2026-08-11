#!/usr/bin/env python3
"""Python V2 conformance adapter (offline candidate · ZCP-21).

Pin: sdk_bootstrap.pins.json → suite_version + design_repo_ref

Usage (repo root):
  .venv/bin/python tests/conformance/run_suite.py
  .venv/bin/python tests/conformance/run_suite.py --report /tmp/v2-report.json
  .venv/bin/pytest tests/conformance -q
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as script from repo root
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.conformance.assert_expect import assert_expects  # noqa: E402
from tests.conformance.handlers import HANDLERS, run_dt_case  # noqa: E402
from tests.conformance.paths import (  # noqa: E402
    load_json,
    load_manifest,
    load_pins,
    resolve_design_root,
)


def _assert_case(case_id: str, observe: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    if case_id == "L2.settings.ai_process_result.001":
        if not observe.get("production_default_false"):
            return ["production.ai_process_result must be false"]
        return []
    if case_id.startswith("DT."):
        return _assert_dt(observe, expect)
    # L1 gte keys
    diffs = assert_expects(observe, expect)
    return diffs


def _assert_dt(observe: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    for key, want in expect.items():
        if key.endswith("_contains") and isinstance(want, str):
            if key == "lineage_contains":
                hay = str(observe.get("lineage_contains") or "")
            elif key == "custom_label_contains":
                hay = str(observe.get("custom_label_contains") or "")
            else:
                hay = str(observe.get(key) or "")
            if want not in hay:
                diffs.append(f"{key}: missing {want!r} in {hay[:120]!r}")
            continue
        if key in (
            "layer_a.required_four",
            "inject_inspect.sent.mini_schema.present",
            "inject_inspect.sent.scope_brief.present",
        ):
            if observe.get(key) is False:
                diffs.append(f"{key}: got False")
            continue
        if key.startswith("diagnosis."):
            got = observe.get(key)
            if got is not None and got != want:
                diffs.append(f"{key}: got {got!r} want {want!r}")
            continue
        if key in observe:
            if observe[key] != want:
                diffs.append(f"{key}: got {observe[key]!r} want {want!r}")
        else:
            if key in (
                "result",
                "error_class",
                "companions_present",
                "has_return",
                "req_id",
                "req_id.present",
                "forged_hash",
                "retryable",
                "decision.policy",
                "decision.reason",
            ):
                diffs.append(f"{key}: missing want {want!r}")
    return diffs


async def _run_one(
    design_root: Path, entry: dict[str, Any]
) -> dict[str, Any]:
    case_id = entry["id"]
    rel = entry["path"]
    case_dir = design_root / "conformance" / rel
    case_path = case_dir / "case.json"
    t0 = time.perf_counter()
    if not case_path.exists():
        return {
            "id": case_id,
            "status": "error",
            "message": f"missing {case_path}",
            "duration_ms": 0,
        }
    case = load_json(case_path)
    try:
        if case_id in HANDLERS:
            fn = HANDLERS[case_id]
            if inspect.iscoroutinefunction(fn):
                observe = await fn(design_root, case_dir, case)
            else:
                observe = fn(design_root, case_dir, case)
        elif case_id.startswith("DT."):
            observe = await run_dt_case(design_root, case_dir, case, case_id)
        else:
            return {
                "id": case_id,
                "status": "skipped",
                "message": "no V2 handler",
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }
        expect = case.get("expect") or {}
        diffs = _assert_case(case_id, observe, expect)
        ms = int((time.perf_counter() - t0) * 1000)
        if diffs:
            return {
                "id": case_id,
                "status": "failed",
                "message": "; ".join(diffs[:8]),
                "duration_ms": ms,
                "expect_diff": {"diffs": diffs, "observe": _safe(observe)},
            }
        return {"id": case_id, "status": "passed", "duration_ms": ms}
    except Exception as exc:  # noqa: BLE001
        return {
            "id": case_id,
            "status": "error",
            "message": str(exc),
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }


def _safe(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)


async def run_suite(
    *,
    levels: set[str] | None = None,
    include_seed: bool = False,
) -> dict[str, Any]:
    pins = load_pins()
    design_root = resolve_design_root(pins)
    manifest = load_manifest(design_root)
    suite_version = manifest.get("suite_version") or (pins.get("suite") or {}).get(
        "suite_version"
    )
    claim = pins.get("claim") or {}
    levels = levels or set((pins.get("suite") or {}).get("required_levels") or ["L0", "L1", "L2"])
    # Always include detective levels for candidate min tapes
    levels = set(levels) | {"L_detective", "L_rewind"}

    started = datetime.now(timezone.utc).isoformat()
    cases_out: list[dict[str, Any]] = []
    for entry in manifest.get("cases") or []:
        st = entry.get("status", "required")
        if st == "seed_assert_only" and not include_seed:
            cases_out.append(
                {
                    "id": entry["id"],
                    "status": "skipped",
                    "message": "seed_assert_only (pass --include-seed)",
                }
            )
            continue
        if entry.get("level") not in levels and not entry["id"].startswith("DT."):
            # still run DT if detective levels requested
            if not (entry.get("level") in levels):
                continue
        # candidate min: all required L0-L2 + DT required/required_rewind
        if st not in ("required", "required_rewind") and st != "required":
            if st not in ("required", "required_rewind"):
                cases_out.append(
                    {"id": entry["id"], "status": "skipped", "message": f"status={st}"}
                )
                continue
        result = await _run_one(design_root, entry)
        cases_out.append(result)

    finished = datetime.now(timezone.utc).isoformat()
    summary = {
        "total": len(cases_out),
        "passed": sum(1 for c in cases_out if c["status"] == "passed"),
        "failed": sum(1 for c in cases_out if c["status"] == "failed"),
        "skipped": sum(1 for c in cases_out if c["status"] == "skipped"),
        "error": sum(1 for c in cases_out if c["status"] == "error"),
    }
    try:
        from zeus_client_v2 import __version__ as v2_ver
    except Exception:
        v2_ver = "2.0.0a0"

    return {
        "suite_version": suite_version,
        "language": "python",
        "package": "kotenai-zeus-client",
        "package_version": v2_ver,
        "client_floor": claim.get("client_floor") or "client-floor-5",
        "claim_level": claim.get("claim_level") or "candidate",
        "design_repo": str(design_root),
        "started_at": started,
        "finished_at": finished,
        "summary": summary,
        "cases": cases_out,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V2 offline conformance adapter")
    ap.add_argument("--levels", default="L0,L1,L2,L_detective,L_rewind")
    ap.add_argument("--include-seed", action="store_true")
    ap.add_argument(
        "--report",
        default=str(_ROOT / "tests" / "conformance" / "last_report.json"),
    )
    args = ap.parse_args(argv)
    levels = {x.strip() for x in args.levels.split(",") if x.strip()}
    report = asyncio.run(run_suite(levels=levels, include_seed=args.include_seed))
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    s = report["summary"]
    print(f"suite_version={report['suite_version']}")
    print(
        f"passed={s['passed']} failed={s['failed']} error={s.get('error', 0)} "
        f"skipped={s['skipped']} total={s['total']}"
    )
    for c in report["cases"]:
        mark = {
            "passed": "OK",
            "failed": "FAIL",
            "error": "ERR",
            "skipped": "SKIP",
        }.get(c["status"], c["status"])
        msg = f" — {c.get('message')}" if c.get("message") and c["status"] != "passed" else ""
        print(f"  [{mark}] {c['id']}{msg}")
    print(f"report={out}")
    if s["failed"] or s.get("error", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
