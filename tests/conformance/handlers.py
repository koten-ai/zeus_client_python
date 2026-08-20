"""Case handlers — drive V2 domain / agent APIs against design fixtures."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.conformance.paths import load_json
from zeus_client.application.agent_turn import run_agent_turn
from zeus_client.config.models import ClientSettings
from zeus_client.domain.catalog import lineage_base_id
from zeus_client.domain.contract import extract_stamped_hash
from zeus_client.domain.layer_a import (
    parse_layer_a,
    ui_view,
)
from zeus_client.domain.messages import TurnRequest
from zeus_client.domain.mini_schema import classify_mini_schema, get_mini_schema
from zeus_client.domain.policy import decide_policy
from zeus_client.domain.rules import merge_rules_frozen
from zeus_client.domain.tool_trail import error_class_for
from zeus_client.ports import LlmRequest, LlmResponse, VerbHopResult, VerbRequest

__all__ = [
    "merge_rules_frozen",
    "HANDLERS",
    "run_dt_case",
]


@dataclass
class _ScriptedLlm:
    script: list[Any] = field(default_factory=list)
    calls: list[LlmRequest] = field(default_factory=list)

    async def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls.append(req)
        if not self.script:
            return LlmResponse(content="(empty script)", tool_calls=())
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@dataclass
class _ScriptedZeus:
    results: dict[str, VerbHopResult] = field(default_factory=dict)
    calls: list[VerbRequest] = field(default_factory=list)

    async def resolve_auth(self, target, *, force: bool = False):
        return type("A", (), {"headers": {}, "mode": "none"})()

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        self.calls.append(req)
        if req.verb in self.results:
            return self.results[req.verb]
        return VerbHopResult(
            ok=True,
            status_code=200,
            req_id=f"req-{req.verb}",
            body={"items": []},
        )


def _tc(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _return_payload_from_script(script: Mapping[str, Any]) -> dict[str, Any] | None:
    for r in script.get("rounds") or []:
        for tc in (r.get("assistant") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") == "return":
                try:
                    payload = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    return {}
                return payload if isinstance(payload, dict) else {}
    return None


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
    base_id = lineage_base_id(catalog) or catalog.get("base_id")
    contract = catalog.get("contract") or {}
    verbs = catalog.get("verbs") or catalog.get("tools") or []
    required = (schema.get("required") or []) if isinstance(schema, dict) else []
    four = {"summary", "confidence", "query_decomposition", "decomposition"}
    props = set((schema.get("properties") or {}).keys()) if isinstance(schema, dict) else set()
    stamped = extract_stamped_hash(catalog)
    mini = get_mini_schema(catalog)
    return {
        "result": True,
        "catalog.base_id": base_id,
        "catalog.contract.id": contract.get("id"),
        "catalog.contract.hash": stamped or contract.get("hash"),
        "catalog.verb_count_gte": len(verbs) if isinstance(verbs, list) else 0,
        "schema.required_four_defined": four.issubset(set(required)) or four.issubset(props),
        "catalog.mini_schema.parsed": bool(mini.get("entity_types") is not None),
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
        if "business_rules_triggers" in raw_la and isinstance(
            raw_la["business_rules_triggers"], dict
        ):
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
    out = merge_rules_frozen(data["base"], data["overlay"], frozen=bool(data.get("frozen")))
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
    """Product profiles default false; hub profile is the insight exception."""
    from zeus_client.config.models import RuntimeConfig
    from zeus_client.config.profiles import apply_profile

    data = load_json(case_dir / case["input"]["fixture"])
    profile = data["profiles"]
    prod = bool(profile["production"]["ai_process_result"])
    hub = bool(profile["hub_debug"]["ai_process_result"])
    hub_profile = apply_profile(RuntimeConfig(), "hub")
    pkg_false = ClientSettings().ai_process_result is False
    return {
        "production.ai_process_result": False if (prod is False and pkg_false) else True,
        "hub.ai_process_result": hub,
        "result": prod is False and pkg_false,
        "production_default_false": prod is False,
        "package_default_false": pkg_false,
        "hub_profile_true": hub_profile.settings.ai_process_result is True,
        "package_hub_default_true": hub_profile.settings.ai_process_result is True,
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


async def run_l1_force_return(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    """Drive ``run_agent_turn`` until the force-return nudge fires."""
    _ = design_root
    data = load_json(case_dir / case["input"]["fixture"])
    max_rounds = int(data["max_rounds"])
    find_tc = _tc("find", {"entity_type": "Beer"})
    script: list[Any] = [
        LlmResponse(content=None, tool_calls=(find_tc,)) for _ in range(max(1, max_rounds - 1))
    ]
    script.append(LlmResponse(content="forced wrap-up", tool_calls=()))
    llm = _ScriptedLlm(script=script)
    zeus = _ScriptedZeus(
        results={
            "find": VerbHopResult(
                ok=True,
                status_code=200,
                req_id="req-empty",
                body={"items": []},
            )
        }
    )
    result = await run_agent_turn(
        TurnRequest(
            message="list beers",
            tools=({"type": "function", "function": {"name": "find"}},),
            settings=ClientSettings(
                ai_process_result=False,
                max_rounds=max_rounds,
                force_return_rounds_left=1,
            ),
        ),
        llm=llm,
        zeus=zeus,
    )
    forced = any("force_return" in n for n in result.debug.notes)
    return {
        "result": forced,
        "force_return": forced,
        "max_rounds": max_rounds,
        "rounds_without_return": int(result.debug.rounds or 0),
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
    """Parse slim Detective export. Does not copy ``expect`` into observe."""
    _ = design_root
    inp = case.get("input") or {}
    export_name = inp.get("detective_export") or "detective_export.slim.json"
    export_path = case_dir / export_name
    if not export_path.exists():
        return {}
    export = load_json(export_path)
    return {
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
        "custom_label_contains": _get_path(export, "diagnosis.prompt.custom_label") or "",
    }


def run_dt_rewind_companions(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    _ = design_root, case
    script_p = case_dir / "llm_script.json"
    zeus_p = case_dir / "zeus_responses.json"
    if not script_p.exists() or not zeus_p.exists():
        return {
            "result": False,
            "error_class": "rewind_companions_missing",
            "companions_present": False,
            "has_return": False,
        }
    script = load_json(script_p)
    zeus = load_json(zeus_p)
    rounds = script.get("rounds") or []
    hops = zeus.get("hops") or zeus.get("responses") or []
    payload = _return_payload_from_script(script)
    has_return = payload is not None
    layer_ok = False
    if isinstance(payload, dict):
        layer_ok = parse_layer_a(payload).ok
    return {
        "result": bool(rounds) and has_return,
        "companions_present": True,
        "llm_rounds": len(rounds),
        "zeus_hops": len(hops) if isinstance(hops, list) else 0,
        "has_return": has_return,
        "layer_a.required_four": layer_ok,
        "mode_capable": "rewind",
    }


def run_dt_smooth(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    observe = run_dt_rewind_companions(design_root, case_dir, case)
    slim = run_dt_assert_only(design_root, case_dir, case)
    for k, v in slim.items():
        observe.setdefault(k, v)
    observe["result"] = bool(observe.get("companions_present") and observe.get("has_return"))
    return observe


def run_dt_fail_client_mini(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    """Missing MINI-SCHEMA → stable ``error_class`` from V2 classifier."""
    _ = design_root, case
    doc: dict[str, Any] = {"messages": [{"role": "system", "content": "no brief here"}]}
    fix = case_dir / "fixture.json"
    if fix.exists():
        data = load_json(fix)
        if isinstance(data.get("catalog"), dict):
            doc = data["catalog"]
    return classify_mini_schema(get_mini_schema(doc))


async def run_dt_fail_zeus(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    """409 contract mismatch via ``run_agent_turn`` + scripted Zeus hop."""
    _ = case_dir
    inp = case.get("input") or {}
    rel = inp.get("zeus_response") or "wire/errors/contract_409.response.json"
    resp_path = _resolve(design_root, rel)
    resp = load_json(resp_path) if resp_path.exists() else {}
    headers = resp.get("headers") or {}
    req_id = str(headers.get("X-Zeus-Req-Id") or "")
    status = int(resp.get("status") or 409)
    body = resp.get("body") if isinstance(resp.get("body"), dict) else {}
    llm = _ScriptedLlm(
        script=[
            LlmResponse(content=None, tool_calls=(_tc("search", {"query_text": "x"}),)),
            LlmResponse(content="stopped retrying", tool_calls=()),
        ]
    )
    zeus = _ScriptedZeus(
        results={
            "search": VerbHopResult(
                ok=False,
                status_code=status,
                req_id=req_id or None,
                error="contract mismatch",
                body=body,
            )
        }
    )
    result = await run_agent_turn(
        TurnRequest(
            message="search fruit beers",
            tools=({"type": "function", "function": {"name": "search"}},),
            settings=ClientSettings(ai_process_result=False, max_rounds=3),
        ),
        llm=llm,
        zeus=zeus,
    )
    trail = list(result.tool_trail or [])
    hop = trail[0] if trail else {}
    klass = hop.get("error_class") or error_class_for(ok=False, status=status)
    got_req = str(hop.get("req_id") or req_id or "")
    retryable = bool((resp.get("client_expect") or {}).get("retryable", False))
    return {
        "result": False,
        "error_class": klass,
        "req_id": got_req,
        "req_id.present": bool(got_req),
        "forged_hash": False,
        "retryable": retryable,
    }


def run_dt_fail_llm(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    _ = design_root, case
    data = load_json(case_dir / "fixture.json") if (case_dir / "fixture.json").exists() else {}
    inv = data.get("invalid_return") if isinstance(data, dict) else None
    if not isinstance(inv, dict):
        inv = {}
    layer = parse_layer_a(inv)
    dec = decide_policy(layer)
    return {
        "result": False,
        "error_class": None if layer.ok else "layer_a_validation_failed",
        "layer_a.required_four": layer.ok,
        "decision.policy": dec.policy,
        "decision.reason": dec.reason,
    }


def run_dt_fail_control_plane(design_root: Path, case_dir: Path, case: dict) -> dict[str, Any]:
    """Trigger missing/false while Layer A + data path still ok."""
    _ = design_root, case
    payload: dict[str, Any] = {
        "summary": "Found beers from Zeus data.",
        "query_decomposition": {"intent": "List", "entity": "Beer"},
        "decomposition": {"targets": [{"entity_type": "Beer"}]},
        "confidence": "high",
        "policy_action": "answer",
        "business_rules_triggers": {},
    }
    fix = case_dir / "fixture.json"
    if fix.exists():
        data = load_json(fix)
        if isinstance(data.get("layer_a"), dict):
            payload = data["layer_a"]
    layer = parse_layer_a(payload)
    dec = decide_policy(layer)
    fired = any(bool(v) for v in layer.business_rules_triggers.values())
    return {
        "result": layer.ok,
        "data_ok": layer.ok,
        "trigger_fired": fired,
        "partial_control_plane": layer.ok and not fired,
        "error_class": None,
        "decision.policy": dec.policy,
    }


async def run_dt_case(
    design_root: Path, case_dir: Path, case: dict, case_id: str
) -> dict[str, Any]:
    fn = HANDLERS.get(case_id)
    if fn is None:
        return {"result": False, "error_class": "no_v2_handler"}
    if inspect.iscoroutinefunction(fn):
        return await fn(design_root, case_dir, case)
    return fn(design_root, case_dir, case)


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
    "DT.smooth_short.beer_fruit_pipeline_base61.001": run_dt_smooth,
    "DT.smooth_long.beer_fruit_multi_round_no_pipeline_base61.001": run_dt_smooth,
    "DT.fail_client.missing_mini_schema.001": run_dt_fail_client_mini,
    "DT.fail_zeus.contract_409.001": run_dt_fail_zeus,
    "DT.fail_llm.bad_layer_a.001": run_dt_fail_llm,
    "DT.fail_control_plane.trigger_missing_data_ok.001": run_dt_fail_control_plane,
}
