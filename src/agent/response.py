"""Extract schema-aligned zeus_data rows from an agent turn trace."""
from dataclasses import dataclass, field
from typing import Any, Optional

from zeus_client.zeus.catalog import get_mini_schema

_DATA_TOOLS = frozenset({"pipeline", "project", "find", "search", "get", "traverse"})
_RESERVED_FIELDS = frozenset({"id", "doc_key", "entity_type"})


@dataclass
class StructuredAgentResponse:
    """Structured payload alongside the natural-language answer."""
    answer: str
    zeus_data: list[dict]
    decomposition: Optional[dict] = None
    return_payload: Optional[dict] = None
    entity_type: Optional[str] = None
    source_tool: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    # base-5 control plane (optional; filled when settings/policy path runs)
    layer_a: Optional[dict] = None
    policy: Optional[str] = None
    ui_text: Optional[str] = None
    ui: Optional[dict] = None
    flags: dict = field(default_factory=dict)
    hooks_jailbreak_score: Optional[float] = None
    artifacts: Optional[dict] = None


def _parse_return_payload(trace: dict) -> dict:
    for step in reversed(trace.get("steps") or []):
        if step.get("type") in ("return", "return_result"):
            args = step.get("args")
            if isinstance(args, dict):
                return args
    return {}


def _decomposition_from_payload(payload: dict) -> Optional[dict]:
    decomp = payload.get("decomposition") or payload.get("query_understanding")
    return decomp if isinstance(decomp, dict) else None


def _entity_type_from_decomposition(decomposition: Optional[dict]) -> Optional[str]:
    if not decomposition:
        return None
    targets = decomposition.get("targets")
    if not isinstance(targets, list):
        return None
    for target in targets:
        if isinstance(target, dict):
            et = target.get("entity_type")
            if isinstance(et, str) and et.strip():
                return et.strip()
    return None


def _entity_type_from_args(name: str, args: dict) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    et = args.get("entity_type")
    if isinstance(et, str) and et.strip():
        return et.strip()
    if name == "pipeline":
        steps = args.get("steps")
        if isinstance(steps, list):
            for step in reversed(steps):
                if isinstance(step, dict):
                    step_et = step.get("entity_type")
                    if isinstance(step_et, str) and step_et.strip():
                        return step_et.strip()
    return None


def _entity_type_from_rows(rows: list[dict]) -> Optional[str]:
    """If all dict rows agree on a non-empty entity_type field, return it."""
    found: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        et = row.get("entity_type")
        if isinstance(et, str) and et.strip():
            found.add(et.strip())
    if len(found) == 1:
        return next(iter(found))
    return None


def _entity_type_from_prior_tools(tool_calls: list, before_index: int) -> Optional[str]:
    """Walk earlier successful data tools for entity_type (common after find → get)."""
    for i in range(before_index - 1, -1, -1):
        tc = tool_calls[i]
        if not isinstance(tc, dict) or tc.get("status") != 200:
            continue
        name = tc.get("name") or ""
        if name not in _DATA_TOOLS:
            continue
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        et = _entity_type_from_args(name, args)
        if et:
            return et
    return None


def _dict_rows(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        return [value]
    return []


# Keys on pipeline `data` that are envelope metadata, not step bindings or row lists.
_PIPELINE_DATA_META_KEYS = frozenset(
    {
        "job_fingerprint",
        "meta",
        "status",
        "confidence",
        "summary",
        "turn_complete",
        "query_decomposition",
        "decomposition",
        "provenance",
        "entity_refs",
        "node_refs",
        "error",
        "warnings",
        "notes",
        "usage",
        "elapsed_ms",
        "total_cost",
        "steps_executed",
        "step_costs",
    }
)
_ROW_LIST_KEYS = ("rows", "items", "results")


def _rows_from_step_output(step_out: Any) -> list[dict]:
    """Extract entity dict rows from a single pipeline step binding value."""
    if isinstance(step_out, list):
        return _dict_rows(step_out)
    if not isinstance(step_out, dict):
        return []
    for key in _ROW_LIST_KEYS:
        rows = _dict_rows(step_out.get(key))
        if rows:
            return rows
    # Nested data envelope under a binding (rare)
    nested = step_out.get("data")
    if nested is not None and nested is not step_out:
        if isinstance(nested, list):
            return _dict_rows(nested)
        if isinstance(nested, dict):
            for key in _ROW_LIST_KEYS:
                rows = _dict_rows(nested.get(key))
                if rows:
                    return rows
    # A single entity-shaped object (has name/id) — not meta-only
    if any(k in step_out for k in ("id", "name", "doc_key", "node_id")):
        return [step_out]
    return []


def _return_binding_names(args: dict, data: dict) -> list[str]:
    """Ordered step `as` names to pull from pipeline data."""
    names: list[str] = []
    ret = args.get("return") if isinstance(args, dict) else None
    if isinstance(ret, list):
        for name in ret:
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    elif isinstance(ret, str) and ret.strip():
        names.append(ret.strip())

    if names:
        return names

    # Infer from pipeline steps' `as` (last step first — usually the projection)
    steps = args.get("steps") if isinstance(args, dict) else None
    if isinstance(steps, list):
        for step in reversed(steps):
            if isinstance(step, dict):
                as_name = step.get("as")
                if isinstance(as_name, str) and as_name.strip():
                    names.append(as_name.strip())
        if names:
            return names

    # Fall back: non-meta keys on data that look like step bindings
    for key, val in data.items():
        if key in _PIPELINE_DATA_META_KEYS or key in _ROW_LIST_KEYS:
            continue
        if isinstance(val, (dict, list)) and _rows_from_step_output(val):
            names.append(key)
    return names


def _rows_from_pipeline_data_dict(data: dict, args: dict) -> list[dict]:
    """Unpack terminating-pipeline `data` envelopes into entity rows.

    Real V2 shape::

        {
          \"job_fingerprint\": {...},
          \"meta\": {...},
          \"status\": \"ok\",
          \"tampa_proj\": {\"rows\": [{\"name\": ...}, ...]}
        }

    Never treat the whole envelope dict as a single entity row.
    """
    # Flat list aliases on data itself
    for key in _ROW_LIST_KEYS:
        rows = _dict_rows(data.get(key))
        if rows:
            return rows

    for name in _return_binding_names(args, data):
        if name not in data:
            continue
        rows = _rows_from_step_output(data.get(name))
        if rows:
            return rows

    # Last resort: first non-meta binding with rows (stable key order)
    for key, val in data.items():
        if key in _PIPELINE_DATA_META_KEYS or key in _ROW_LIST_KEYS:
            continue
        rows = _rows_from_step_output(val)
        if rows:
            return rows

    return []


def _rows_from_pipeline_result(result_json: dict, args: dict) -> list[dict]:
    data = result_json.get("data")
    if data is not None:
        if isinstance(data, list):
            return _dict_rows(data)
        if isinstance(data, dict):
            rows = _rows_from_pipeline_data_dict(data, args if isinstance(args, dict) else {})
            if rows:
                return rows
            # Do NOT fall back to _dict_rows(data) — that wraps the entire
            # envelope as one fake entity and empties zeus_data after schema filter.

    return_names = args.get("return") if isinstance(args, dict) else None
    if isinstance(return_names, list):
        result_block = result_json.get("result")
        if isinstance(result_block, dict):
            for name in reversed(return_names):
                if not isinstance(name, str):
                    continue
                rows = _rows_from_step_output(result_block.get(name))
                if rows:
                    return rows

    result_block = result_json.get("result")
    if isinstance(result_block, dict):
        # Named bindings under result (non-terminating / older shapes)
        if isinstance(return_names, list):
            for name in reversed(return_names):
                if isinstance(name, str) and name in result_block:
                    rows = _rows_from_step_output(result_block.get(name))
                    if rows:
                        return rows
        for key in _ROW_LIST_KEYS:
            rows = _dict_rows(result_block.get(key))
            if rows:
                return rows
        # Scan non-list keys for step bindings
        for key, val in result_block.items():
            if key in _ROW_LIST_KEYS or key in _PIPELINE_DATA_META_KEYS:
                continue
            rows = _rows_from_step_output(val)
            if rows:
                return rows
    return []


def _extract_rows_from_result(result_json: Any, tool_name: str = "", args: Optional[dict] = None) -> list[dict]:
    if not isinstance(result_json, dict):
        return []

    args = args or {}
    if tool_name == "pipeline" or result_json.get("data") is not None:
        rows = _rows_from_pipeline_result(result_json, args)
        if rows:
            return rows

    result_block = result_json.get("result")
    if isinstance(result_block, dict):
        for key in ("items", "rows", "results"):
            rows = _dict_rows(result_block.get(key))
            if rows:
                return rows

    for key in ("rows", "items", "results"):
        rows = _dict_rows(result_json.get(key))
        if rows:
            return rows

    return []


def _select_row_source(trace: dict, return_payload: dict) -> tuple[list[dict], Optional[str], Optional[str]]:
    tool_calls = trace.get("tool_calls") or []
    for idx in range(len(tool_calls) - 1, -1, -1):
        tc = tool_calls[idx]
        if not isinstance(tc, dict) or tc.get("status") != 200:
            continue
        name = tc.get("name") or ""
        if name not in _DATA_TOOLS:
            continue
        result_json = tc.get("result_json")
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        rows = _extract_rows_from_result(result_json, name, args)
        if rows:
            entity_type = _entity_type_from_args(name, args)
            if not entity_type:
                entity_type = _entity_type_from_rows(rows)
            if not entity_type:
                entity_type = _entity_type_from_prior_tools(tool_calls, idx)
            return rows, name, entity_type

    evidence = return_payload.get("evidence")
    if isinstance(evidence, list):
        rows = _dict_rows(evidence)
        if rows:
            entity_type = _entity_type_from_rows(rows)
            return rows, "return", entity_type

    return [], None, None


def _normalize_output_schema_arg(output_schema: Any) -> Optional[dict[str, list[str]]]:
    if not output_schema:
        return None
    if not isinstance(output_schema, dict):
        return None

    if "fields" in output_schema:
        et = output_schema.get("entity_type")
        fields = output_schema.get("fields")
        if isinstance(et, str) and isinstance(fields, list):
            return {et: [str(f) for f in fields]}
        return None

    out: dict[str, list[str]] = {}
    for key, val in output_schema.items():
        if isinstance(key, str) and isinstance(val, list):
            out[key] = [str(f) for f in val]
    return out or None


def _injection_output_schema(chat_req: dict) -> Optional[dict[str, list[str]]]:
    guidance = chat_req.get("guidance") or {}
    injections = guidance.get("injections") or {}
    schema = injections.get("output_schema")
    return _normalize_output_schema_arg(schema)


def _fk_field_names(entity_def: dict) -> set[str]:
    fields = (entity_def or {}).get("fields") or {}
    return {
        name for name, meta in fields.items()
        if isinstance(meta, dict) and meta.get("kind") == "entity_fk"
    }


def resolve_field_allowlist(
    chat_req: dict,
    entity_type: Optional[str],
    output_schema: Any = None,
) -> tuple[set[str], set[str], list[str]]:
    """Return (allowed_fields, fk_prefixes, warnings) for schema filtering."""
    warnings: list[str] = []
    override = _normalize_output_schema_arg(output_schema)
    if override is None:
        override = _injection_output_schema(chat_req)

    if override and entity_type and entity_type in override:
        allowed = set(override[entity_type]) | _RESERVED_FIELDS
        return allowed, set(), warnings

    if override and not entity_type and len(override) == 1:
        only_et = next(iter(override))
        allowed = set(override[only_et]) | _RESERVED_FIELDS
        return allowed, set(), warnings

    mini = get_mini_schema(chat_req)
    entity_types = mini.get("entity_types") or {}
    if not entity_types:
        warnings.append("zeus_data: no MINI-SCHEMA available to validate fields")
        return set(), set(), warnings

    if entity_type and entity_type in entity_types:
        ent = entity_types[entity_type]
        allowed = set((ent.get("fields") or {}).keys()) | _RESERVED_FIELDS
        fk_prefixes = _fk_field_names(ent)
        return allowed, fk_prefixes, warnings

    if not entity_type:
        warnings.append("zeus_data: entity_type unknown; cannot resolve MINI-SCHEMA fields")
        return set(), set(), warnings

    warnings.append(f"zeus_data: entity_type '{entity_type}' not found in MINI-SCHEMA")
    return set(), set(), warnings


def _field_allowed(key: str, allowed: set[str], fk_prefixes: set[str]) -> bool:
    if key in _RESERVED_FIELDS:
        return True
    if key in allowed:
        return True
    if "." in key:
        prefix = key.split(".", 1)[0]
        if prefix in fk_prefixes:
            return True
    return False


def filter_rows_to_schema(
    rows: list[dict],
    allowed: set[str],
    fk_prefixes: set[str],
    entity_type: Optional[str],
) -> tuple[list[dict], list[str]]:
    if not allowed and not fk_prefixes:
        return [], []

    warnings: list[str] = []
    seen_warnings: set[str] = set()
    filtered: list[dict] = []
    et_label = entity_type or "unknown"

    for row in rows:
        if not isinstance(row, dict):
            continue
        out: dict = {}
        for key, val in row.items():
            if _field_allowed(key, allowed, fk_prefixes):
                out[key] = val
            else:
                msg = f"zeus_data: dropped unknown field '{key}' on entity {et_label}"
                if msg not in seen_warnings:
                    seen_warnings.add(msg)
                    warnings.append(msg)
        if out:
            filtered.append(out)

    return filtered, warnings


def extract_structured_response(
    answer: str,
    trace: dict,
    chat_req: dict,
    *,
    output_schema: Any = None,
    settings: Any = None,
    hooks_jailbreak_score: Optional[float] = None,
    hooks_must_refuse: bool = False,
    apply_policy: Optional[bool] = None,
) -> StructuredAgentResponse:
    """Build a StructuredAgentResponse from a completed agent turn.

    Layer A parse + Client policy table run when ``apply_policy`` is True, or
    when ``settings`` is provided (base-5 floor). Default off preserves
    pre-0.2 structured extraction behavior.
    """
    from zeus_client.agent.layer_a import parse_layer_a
    from zeus_client.agent.policy import decide_policy
    from zeus_client.agent.settings import ClientSettings, prepare_settings

    return_payload = _parse_return_payload(trace)
    decomposition = _decomposition_from_payload(return_payload)

    raw_rows, source_tool, entity_type = _select_row_source(trace, return_payload)
    if not entity_type:
        entity_type = _entity_type_from_decomposition(decomposition)
    if not entity_type and raw_rows:
        # Last resort: row payload may carry entity_type even when tools/args did not.
        entity_type = _entity_type_from_rows(raw_rows)

    allowed, fk_prefixes, schema_warnings = resolve_field_allowlist(
        chat_req, entity_type, output_schema,
    )

    if raw_rows and allowed:
        zeus_data, filter_warnings = filter_rows_to_schema(
            raw_rows, allowed, fk_prefixes, entity_type,
        )
    elif raw_rows and not allowed:
        zeus_data = []
        filter_warnings = []
    else:
        zeus_data = []
        filter_warnings = []

    warnings = schema_warnings + filter_warnings

    layer_a_dict = None
    policy = None
    ui_text = None
    ui = None
    flags: dict = {}
    artifacts = None
    hscore = hooks_jailbreak_score
    final_answer = answer or ""

    run_policy = apply_policy if apply_policy is not None else (settings is not None)
    if run_policy and return_payload:
        try:
            cs = prepare_settings(settings) if settings is not None else ClientSettings()
        except Exception as exc:
            warnings.append(f"settings_prepare_failed: {exc}")
            cs = ClientSettings()
        rule_ids = list((cs.rules or {}).keys()) if cs.rules else None
        layer = parse_layer_a(
            return_payload,
            rule_ids=rule_ids,
            allow_array_triggers=cs.allow_array_triggers,
            output_request=cs.output_request,
            app_output_on_error=cs.app_output_on_error,
        )
        warnings.extend(layer.warnings)
        warnings.extend(layer.errors)
        brand = bool(cs.company_context) or bool((cs.messages or {}).get("message_brand"))
        decision = decide_policy(
            layer,
            settings=cs,
            hooks_jailbreak_score=float(hscore or 0.0),
            hooks_must_refuse=hooks_must_refuse,
            brand_inject_present=brand,
        )
        layer_a_dict = {
            "summary": layer.summary,
            "query_decomposition": layer.query_decomposition,
            "decomposition": layer.decomposition,
            "confidence": layer.confidence,
            "policy_action": layer.policy_action,
            "business_rules_triggers": layer.business_rules_triggers,
            "app_output": layer.app_output,
            "jail_break_attempt": layer.jail_break_attempt,
            "errors": layer.errors,
            "warnings": layer.warnings,
            "ok": layer.ok,
        }
        policy = decision.policy
        ui_text = decision.ui_text
        ui = decision.ui(layer)
        flags = decision.flags
        hscore = decision.hooks_jailbreak_score
        artifacts = decision.artifacts(layer)
        # Prefer policy chrome for user-facing answer when refuse/error forced
        if decision.forced and decision.policy in ("refuse", "error"):
            final_answer = decision.ui_text
        elif not final_answer and decision.ui_text:
            final_answer = decision.ui_text
        if decision.soft_require_policy_action_missing:
            warnings.append("soft_require: policy_action missing with brand inject present")

    return StructuredAgentResponse(
        answer=final_answer,
        zeus_data=zeus_data,
        decomposition=decomposition,
        return_payload=return_payload or None,
        entity_type=entity_type,
        source_tool=source_tool,
        warnings=warnings,
        layer_a=layer_a_dict,
        policy=policy,
        ui_text=ui_text,
        ui=ui,
        flags=flags,
        hooks_jailbreak_score=hscore,
        artifacts=artifacts,
    )