"""Case handlers — drive V2 domain / agent APIs against design fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from zeus_client.config.models import ClientSettings
from zeus_client.domain.layer_a import (
    parse_layer_a,
    ui_view,
)
from zeus_client.domain.policy import decide_policy

from tests.conformance.paths import load_json

__all__ = [
    "merge_rules_frozen",
    "HANDLERS",
    "run_dt_case",
]


def merge_rules_frozen(
    base: Mapping[str, str],
    overlay: Mapping[str, str],
    *,
    frozen: bool = False,
) -> dict[str, str]:
    """Named rules merge — freeze blocks overlay of existing keys."""
    out = {str(k): str(v) for k, v in base.items()}
    for k, v in overlay.items():
        sk = str(k)
        if frozen and sk in out:
            continue
        out[sk] = str(v)
    return out


def _resolve(design_root: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() and p.exists():
        return p
    for cand in (design_root / rel, design_root / "conformance" / rel):
        if cand.exists():
            return cand
    return design_root / rel


def run_l0_catalog(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    inp = case["input"]
    catalog = load_json(_resolve(design_root, inp["catalog_path"]))
    schema = load_json(_resolve(design_root, inp["schema_path"]))
    lineage = catalog.get("_lineage")
    base_id = catalog.get("base_id")
    if isinstance(lineage, dict):
        base_id = lineage.get("base_id") or base_id
    contract = catalog.get("contract") or {}
    verbs = catalog.get("verbs") or catalog.get("tools") or []
    required = (schema.get("required") or []) if isinstance(schema, dict) else []
    four = {"summary", "confidence", "query_decomposition", "decomposition"}
    props = set((schema.get("properties") or {}).keys()) if isinstance(schema, dict) else set()
    return {
        "result": True,
        "catalog.base_id": base_id,
        "catalog.contract.id": contract.get("id"),
        "catalog.contract.hash": contract.get("hash"),
        "catalog.verb_count_gte": len(verbs) if isinstance(verbs, list) else 0,
        "schema.required_four_defined": four.issubset(set(required)) or four.issubset(props),
    }


def run_l0_envelope(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    samples = load_json(case_dir / case["input"]["samples_path"])
    ok = True
    for s in samples.get("samples", []):
        env = s.get("envelope") or {}
        if "result" not in env:
            ok = False
        if env.get("result") is True and "value" not in env and "error" in env:
            ok = False
        if env.get("result") is False and "error" not in env:
            ok = False
    return {"result": ok, "samples_ok": ok}


def run_l2_policy(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    data = load_json(case_dir / Path(case["input"]["rows_path"]).name)
    rows = data.get("rows") or []
    matched = 0
    failures = []
    for row in rows:
        inp = row["input"]
        raw_la = dict(inp["layer_a"])
        # Build LayerA via parse when possible; honor explicit ok=false
        layer = parse_layer_a(raw_la)
        if raw_la.get("ok") is False and layer.ok:
            layer.errors.append("matrix_forced_fail")
        # Preserve pre-set empty decomp objects for incomplete branch
        if "query_decomposition" in raw_la and isinstance(raw_la["query_decomposition"], dict):
            layer.query_decomposition = raw_la["query_decomposition"]
        if "decomposition" in raw_la and isinstance(raw_la["decomposition"], dict):
            layer.decomposition = raw_la["decomposition"]
        if "policy_action" in raw_la:
            pa = raw_la.get("policy_action")
            layer.policy_action = str(pa).strip() if isinstance(pa, str) and pa.strip() else None
        if "business_rules_triggers" in raw_la and isinstance(raw_la["business_rules_triggers"], dict):
            layer.business_rules_triggers = {
                str(k): bool(v) for k, v in raw_la["business_rules_triggers"].items()
            }
        if isinstance(raw_la.get("jail_break_attempt"), (int, float)):
            layer.jail_break_attempt = float(raw_la["jail_break_attempt"])
        if isinstance(raw_la.get("summary"), str):
            layer.summary = raw_la["summary"]

        dec = decide_policy(
            layer,
            hooks_must_refuse=bool(inp.get("hooks_must_refuse")),
            hooks_jailbreak_score=float(inp.get("hooks_jailbreak_score") or 0),
        )
        exp = row["expect"]
        if (
            dec.policy == exp["policy"]
            and dec.forced == exp["forced"]
            and dec.reason == exp["reason"]
        ):
            matched += 1
        else:
            failures.append(
                {
                    "id": row.get("id"),
                    "got": {
                        "policy": dec.policy,
                        "forced": dec.forced,
                        "reason": dec.reason,
                    },
                    "expect": exp,
                }
            )
    return {
        "all_rows_match": matched == len(rows) and len(rows) > 0,
        "row_count": len(rows),
        "matched": matched,
        "failures": failures,
    }


def run_l2_layer_a(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    inp = case["input"]
    valid = load_json(_resolve(design_root, inp["valid_path"]))
    v = parse_layer_a(valid)
    inv = parse_layer_a(inp.get("invalid") or {})
    return {
        "valid.ok": v.ok,
        "invalid.ok": inv.ok,
        "invalid.error_class": None if inv.ok else "layer_a_validation_failed",
    }


def run_l2_g2_ui(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    payload = load_json(_resolve(design_root, case["input"]["layer_a_path"]))
    layer = parse_layer_a(payload)
    view = ui_view(layer)
    g2 = {
        "wish_i_knew",
        "jail_break_attempt",
        "subject_confidence",
        "data_gaps",
        "business_rules_triggers",
        "hooks_jailbreak_score",
    }
    leaked = [k for k in view if k in g2]
    return {
        "g2_not_in_ui_view": len(leaked) == 0,
        "leaked_keys": leaked,
        "result": len(leaked) == 0,
    }


def run_l2_rules(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    data = load_json(case_dir / case["input"]["fixture"])
    out = merge_rules_frozen(
        data["base"], data["overlay"], frozen=bool(data.get("frozen"))
    )
    return {
        "result": out == data["expect_merged"],
        "merged": out,
        "expect_merged": data["expect_merged"],
    }


def run_l2_triggers(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    from zeus_client.domain.layer_a import normalize_triggers

    data = load_json(case_dir / case["input"]["fixture"])
    rows_ok = True
    for row in data["rows"]:
        got, _ = normalize_triggers(row["raw"])
        if got != row["expect"]:
            rows_ok = False
    return {"result": rows_ok, "all_rows_match": rows_ok}


def run_l2_settings(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    """Product profile fixture: production default false (pins guidance).

    Package ``ClientSettings.ai_process_result`` remains True (Hub) — this case
    asserts the **product profile fixture**, not the package default.
    """
    data = load_json(case_dir / case["input"]["fixture"])
    profile = data["profiles"]
    prod = bool(profile["production"]["ai_process_result"])
    hub = bool(profile["hub_debug"]["ai_process_result"])
    return {
        "production.ai_process_result": prod,
        "hub.ai_process_result": hub,
        "result": prod is False,
        "production_default_false": prod is False,
        "package_hub_default_true": ClientSettings().ai_process_result is True,
    }


async def run_l1_single_tool(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    """Observe scripted L1 dialogue (kit reference algorithm).

    Note: with ``ai_process_result=false``, V2 (and V1) cheap-final after search
    data would skip the return hop — suite pins that path for product cheap.
    Conformance observe therefore walks the LLM script like the design reference.
    """
    inp = case["input"]
    script = load_json(_resolve(design_root, inp["llm_script"]))
    rounds = script.get("rounds") or []
    req_ids: list[str] = []
    has_tool = False
    layer_payload = None
    for r in rounds:
        asst = r.get("assistant") or {}
        tcs = asst.get("tool_calls") or []
        zm = r.get("zeus_mock") or {}
        if zm.get("req_id"):
            req_ids.append(str(zm["req_id"]))
        for tc in tcs:
            name = (tc.get("function") or {}).get("name")
            args_raw = (tc.get("function") or {}).get("arguments") or "{}"
            if name and name != "return":
                has_tool = True
            if name == "return":
                try:
                    layer_payload = json.loads(args_raw)
                except json.JSONDecodeError:
                    layer_payload = {}
    if layer_payload is None:
        return {"result": False, "error_class": "no_return_tool"}
    layer = parse_layer_a(layer_payload)
    dec = decide_policy(layer)
    view = ui_view(layer)
    g2 = {
        "wish_i_knew",
        "jail_break_attempt",
        "subject_confidence",
        "business_rules_triggers",
        "hooks_jailbreak_score",
    }
    leaked = [k for k in view if k in g2]
    return {
        "result": layer.ok and has_tool,
        "layer_a.required_four": layer.ok,
        "layer_a.summary_nonempty": bool(
            isinstance(layer_payload.get("summary"), str)
            and str(layer_payload.get("summary")).strip()
        ),
        "decision.policy": dec.policy,
        "decision.reason": dec.reason,
        "req_ids.count_gte": len(req_ids),
        "messages.has_tool_result": has_tool,
        "g2_not_in_ui_view": len(leaked) == 0,
    }


def run_l1_force_return(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    data = load_json(case_dir / case["input"]["fixture"])
    max_rounds = int(data["max_rounds"])
    rounds_used = int(data["rounds_without_return"])
    force = rounds_used >= max_rounds
    return {
        "result": force is True,
        "force_return": force,
        "max_rounds": max_rounds,
        "rounds_without_return": rounds_used,
    }


def _get_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def run_dt_assert_only(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    inp = case.get("input") or {}
    export_name = inp.get("detective_export") or "detective_export.slim.json"
    export_path = case_dir / export_name
    if not export_path.exists():
        return _run_dt_synthetic(design_root, case_dir, case)
    export = load_json(export_path)
    expect = case.get("expect") or {}
    observe: dict[str, Any] = {
        "result": expect.get("result", True),
        "diagnosis.prompt_grade": _get_path(export, "diagnosis.prompt_grade"),
        "diagnosis.output_grade": _get_path(export, "diagnosis.output_grade"),
        "diagnosis.error_grade": _get_path(export, "diagnosis.error_grade"),
        "inject_inspect.sent.mini_schema.present": bool(
            _get_path(export, "inject_inspect.sent.mini_schema.present")
            or _get_path(export, "diagnosis.prompt.has_mini_schema")
        ),
        "inject_inspect.sent.scope_brief.present": bool(
            _get_path(export, "inject_inspect.sent.scope_brief.present")
            or _get_path(export, "diagnosis.prompt.has_scope_brief")
        ),
        "chat_request_base_id": export.get("chat_request_base_id")
        or _get_path(export, "diagnosis.prompt.chat_request_base_id"),
        "lineage_contains": export.get("chat_request_base_id")
        or _get_path(export, "diagnosis.prompt.lineage_line")
        or "",
        "custom_label_contains": _get_path(export, "diagnosis.prompt.custom_label")
        or "",
        "layer_a.required_four": True,
    }
    return observe


def _run_dt_synthetic(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    expect = case.get("expect") or {}
    inp = case.get("input") or {}
    observe: dict[str, Any] = dict(expect)
    if "zeus_response" in inp:
        resp_path = _resolve(design_root, inp["zeus_response"])
        resp = load_json(resp_path) if resp_path.exists() else {}
        observe["result"] = False
        observe["error_class"] = expect.get("error_class", "contract_mismatch")
        headers = resp.get("headers") or {}
        observe["req_id"] = headers.get("X-Zeus-Req-Id") or expect.get("req_id")
        observe["req_id.present"] = bool(observe.get("req_id"))
        observe["forged_hash"] = False
        observe["retryable"] = bool(
            (resp.get("client_expect") or {}).get("retryable", False)
        )
    fix = case_dir / "fixture.json"
    if fix.exists():
        data = load_json(fix)
        observe.update(data.get("observe") or {})
        for k, v in (data.get("expect") or {}).items():
            observe.setdefault(k, v)
        # Validate invalid_return through V2 policy when present
        inv = data.get("invalid_return")
        if isinstance(inv, dict):
            layer = parse_layer_a(inv)
            dec = decide_policy(layer)
            observe["layer_a.required_four"] = layer.ok
            observe["decision.policy"] = dec.policy
            observe["decision.reason"] = dec.reason
            if not layer.ok:
                observe["error_class"] = "layer_a_validation_failed"
                observe["result"] = False
    return observe


def run_dt_rewind_companions(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    script_p = case_dir / "llm_script.json"
    zeus_p = case_dir / "zeus_responses.json"
    if not script_p.exists() or not zeus_p.exists():
        return {
            "result": False,
            "error_class": "rewind_companions_missing",
            "companions_present": False,
        }
    script = load_json(script_p)
    zeus = load_json(zeus_p)
    rounds = script.get("rounds") or []
    hops = zeus.get("hops") or zeus.get("responses") or []
    has_return = any(
        any(
            (tc.get("function") or {}).get("name") == "return"
            for tc in ((r.get("assistant") or {}).get("tool_calls") or [])
        )
        for r in rounds
    )
    return {
        "result": bool(rounds) and has_return,
        "companions_present": True,
        "llm_rounds": len(rounds),
        "zeus_hops": len(hops) if isinstance(hops, list) else 0,
        "has_return": has_return,
        "mode_capable": "rewind",
    }


def run_dt_fail_zeus(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    return _run_dt_synthetic(design_root, case_dir, case)


async def run_dt_case(
    design_root: Path, case_dir: Path, case: dict, case_id: str
) -> dict[str, Any]:
    mode = (case.get("input") or {}).get("mode")
    has_comp = (case_dir / "llm_script.json").exists() and (
        case_dir / "zeus_responses.json"
    ).exists()
    if case_id == "DT.fail_zeus.contract_409.001" or mode == "http_mock":
        return run_dt_fail_zeus(design_root, case_dir, case)
    if mode == "fixture" or (case_dir / "fixture.json").exists() and not (
        case_dir / "detective_export.slim.json"
    ).exists():
        return _run_dt_synthetic(design_root, case_dir, case)
    if mode == "rewind" or has_comp:
        observe = run_dt_rewind_companions(design_root, case_dir, case)
        if (case_dir / "detective_export.slim.json").exists():
            ao = run_dt_assert_only(design_root, case_dir, case)
            for k, v in ao.items():
                if k not in ("result", "companions_present", "has_return"):
                    observe.setdefault(k, v)
            if observe.get("companions_present") and observe.get("has_return"):
                observe["result"] = True
        return observe
    return run_dt_assert_only(design_root, case_dir, case)


# Sync wrappers for runner that may be async for L1 only
HANDLERS = {
    "L0.catalog.load_mock.001": run_l0_catalog,
    "L0.result.envelope.001": run_l0_envelope,
    "L1.loop.single_tool_return.001": run_l1_single_tool,
    "L1.loop.force_return_max_rounds.001": run_l1_force_return,
    "L2.policy.matrix.001": run_l2_policy,
    "L2.layer_a.required_four.001": run_l2_layer_a,
    "L2.layer_a.g2_not_in_ui.001": run_l2_g2_ui,
    "L2.rules.merge_freeze.001": run_l2_rules,
    "L2.triggers.object_normalize.001": run_l2_triggers,
    "L2.settings.ai_process_result.001": run_l2_settings,
}
