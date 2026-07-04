"""Pipeline step span expansion for trace UI."""
import json

def pipeline_step_spans(tool_at, tool_ms, tc_args, parsed_result):
    """Expand one pipeline HTTP call into per-step waterfall spans.

    Zeus returns per-step timing in ``meta.step_costs``; the Trace UI
    shows each step as its own bar so you can see what the DAG did.
    Falls back to a single ``tool.pipeline`` span when costs are missing.
    """
    step_costs = []
    meta = {}
    if isinstance(parsed_result, dict):
        meta = parsed_result.get("meta") or {}
        step_costs = meta.get("step_costs") or []

    verbs = {}
    for step in (tc_args or {}).get("steps") or []:
        if isinstance(step, dict):
            name = step.get("name") or step.get("as")
            if name:
                verbs[name] = step.get("verb") or ""

    if not step_costs:
        return [{"name": "tool.pipeline", "cls": "tool", "at": tool_at, "ms": tool_ms}]

    spans = []
    offset = 0
    for sc in step_costs:
        step_name = sc.get("as") or sc.get("name") or "step"
        verb = verbs.get(step_name) or ""
        step_ms = int(sc.get("ms") or 0)
        label = f"pipeline.{step_name}"
        if verb:
            label += f".{verb}"
        detail_bits = []
        if sc.get("cost") is not None:
            detail_bits.append(f"cost {sc['cost']}")
        if sc.get("result_size") is not None:
            detail_bits.append(f"{sc['result_size']} rows")
        if sc.get("status"):
            detail_bits.append(sc["status"])
        spans.append({
            "name": label,
            "cls": "tool",
            "at": tool_at + offset,
            "ms": step_ms,
            "detail": " · ".join(detail_bits) if detail_bits else None,
            "pipeline_step": step_name,
            "verb": verb or None,
            "cost": sc.get("cost"),
            "result_size": sc.get("result_size"),
            "status": sc.get("status"),
        })
        offset += step_ms

    overhead = int(tool_ms) - offset
    if overhead > 0:
        spans.append({
            "name": "pipeline.overhead",
            "cls": "tool",
            "at": tool_at + offset,
            "ms": overhead,
            "detail": "HTTP / orchestration",
        })
    return spans


def _pipeline_step_costs(step):
    """Return Zeus per-step costs for a pipeline tool step, if present."""
    costs = step.get("pipeline_step_costs")
    if costs:
        return costs
    for key in ("result_full", "result"):
        raw = step.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        costs = (data.get("meta") or {}).get("step_costs")
        if costs:
            return costs
        if step.get("name") == "pipeline" and data.get("status") not in (None, "ok"):
            return [{"status": data.get("status")}]
    plan = (step.get("args") or {}).get("steps") or []
    return [{"as": s.get("name"), "status": "planned"} for s in plan if isinstance(s, dict)]
