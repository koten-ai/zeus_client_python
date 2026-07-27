"""Extract schema-aligned zeus_data rows from an agent turn trace."""
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Optional

from zeus_client.agent.control_plane import PolicyResult, apply_policy_table
from zeus_client.agent.layer_a import LayerABag, parse_layer_a
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
    # base-5 / base-5.2 Layer A (ZC-WISH-004…012) — G2 never chat UI
    layer_a: Optional[LayerABag] = None
    # base-5 post-terminate policy table (ZC-WISH-010) — optional
    policy: Optional[PolicyResult] = None


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


def _rows_from_pipeline_result(result_json: dict, args: dict) -> list[dict]:
    data = result_json.get("data")
    if data is not None:
        if isinstance(data, list):
            return _dict_rows(data)
        if isinstance(data, dict):
            for key in ("rows", "items", "results"):
                rows = _dict_rows(data.get(key))
                if rows:
                    return rows
            return _dict_rows(data)

    return_names = args.get("return") if isinstance(args, dict) else None
    if isinstance(return_names, list):
        result_block = result_json.get("result")
        if isinstance(result_block, dict):
            for name in reversed(return_names):
                if not isinstance(name, str):
                    continue
                step_out = result_block.get(name)
                if isinstance(step_out, dict):
                    for key in ("rows", "items", "results"):
                        rows = _dict_rows(step_out.get(key))
                        if rows:
                            return rows
                    rows = _dict_rows(step_out)
                    if rows:
                        return rows
                rows = _dict_rows(step_out)
                if rows:
                    return rows

    result_block = result_json.get("result")
    if isinstance(result_block, dict):
        for key in ("rows", "items", "results"):
            rows = _dict_rows(result_block.get(key))
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
    dual_read_array_triggers: bool = True,
    apply_policy: bool = False,
    hooks_jailbreak_score: float = 0.0,
    hooks_must_refuse: bool = False,
    message_map: Optional[Mapping[str, str]] = None,
    output_request: Any = None,
    sticky_flags: Optional[MutableMapping[str, bool]] = None,
) -> StructuredAgentResponse:
    """Build a StructuredAgentResponse from a completed agent turn.

    When ``apply_policy`` is True, runs the Client policy table (ZC-WISH-010)
    and prefers G1 ``policy.ui_text`` for :attr:`StructuredAgentResponse.answer`.
    """
    return_payload = _parse_return_payload(trace)
    layer_a = parse_layer_a(
        return_payload or None,
        dual_read_array_triggers=dual_read_array_triggers,
    )
    decomposition = _decomposition_from_payload(return_payload)
    if decomposition is None and isinstance(layer_a.decomposition, dict):
        decomposition = layer_a.decomposition
    # Prefer query_decomposition intent path when older decomposition is thin
    if decomposition is None and isinstance(layer_a.query_decomposition, dict):
        decomposition = layer_a.query_decomposition

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

    # G1 answer: prefer model summary when caller left answer empty (ZC-WISH-012)
    g1 = layer_a.g1_answer(answer or "")
    warnings = schema_warnings + filter_warnings + list(layer_a.warnings) + list(layer_a.shape_errors)
    if layer_a.missing_required:
        warnings.append(
            "layer_a: missing required " + ", ".join(layer_a.missing_required)
        )

    policy: Optional[PolicyResult] = None
    if apply_policy:
        # Prefer explicit output_request; else guidance / settings on catalog
        oreq = output_request
        if oreq is None and isinstance(chat_req, dict):
            oreq = (chat_req.get("guidance") or {}).get("output_request")
            if oreq is None:
                oreq = chat_req.get("output_request")
        policy = apply_policy_table(
            layer_a,
            hooks_jailbreak_score=hooks_jailbreak_score,
            hooks_must_refuse=hooks_must_refuse,
            message_map=message_map,
            output_request=oreq,
            sticky_flags=sticky_flags,
        )
        g1 = policy.ui_text or g1
        warnings.extend(policy.app_output_errors)
        if policy.reasons:
            warnings.append("policy: " + ", ".join(policy.reasons))

    return StructuredAgentResponse(
        answer=g1,
        zeus_data=zeus_data,
        decomposition=decomposition,
        return_payload=return_payload or None,
        entity_type=entity_type,
        source_tool=source_tool,
        warnings=warnings,
        layer_a=layer_a,
        policy=policy,
    )