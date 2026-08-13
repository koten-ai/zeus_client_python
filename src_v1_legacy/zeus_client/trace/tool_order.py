"""Tool-order helpers for the trace panel chart axes."""
from __future__ import annotations

from zeus_client.constants import normalize_api_version, v2_tool_order
from zeus_client.trace.pipeline import _pipeline_step_costs


def tool_names_from_step(step):
    """Tool / verb names invoked by one trace step (pipeline → inner verbs)."""
    if step.get("type") != "tool":
        return []
    name = step.get("name")
    if name == "pipeline":
        names = []
        args = step.get("args") or {}
        steps_plan = args.get("steps") or []
        if not steps_plan and step.get("pipeline_json"):
            steps_plan = step.get("pipeline_json", {}).get("steps") or []
        by_name = {
            s.get("name"): s for s in steps_plan
            if isinstance(s, dict) and s.get("name")
        }
        for sc in _pipeline_step_costs(step) or []:
            key = sc.get("as") or sc.get("name")
            verb = (by_name.get(key) or {}).get("verb") or key
            if verb:
                names.append(verb)
        if not names:
            for s in steps_plan:
                if isinstance(s, dict) and s.get("verb"):
                    names.append(s["verb"])
        return names
    return [name] if name else []


def build_v1_tool_order_from_chats(chats=None):
    """V1 x-axis: first-seen tool names from a host chat store mapping."""
    chats = chats or {}
    order, seen = [], set()

    def add(nm):
        if nm and nm not in seen:
            seen.add(nm)
            order.append(nm)

    for _cid, chat in sorted(chats.items(), key=lambda kv: kv[1].get("created", 0)):
        for tr in chat.get("traces", []):
            if normalize_api_version(tr.get("api_version")) != "v1":
                continue
            for step in (tr.get("trace") or {}).get("steps", []):
                for nm in tool_names_from_step(step):
                    add(nm)
        if normalize_api_version(
                (chat.get("traces") or [{}])[-1].get("api_version") if chat.get("traces") else "v2") != "v1":
            continue
        for turn in chat.get("turns", []):
            if turn.get("role") != "assistant":
                continue
            for tc in turn.get("tool_calls") or []:
                add((tc.get("function") or {}).get("name"))
    return order


def build_tool_order(chats=None):
    """Return canonical tool-order axes for the trace frequency chart."""
    return {"v1": build_v1_tool_order_from_chats(chats), "v2": v2_tool_order()}