"""Layer A terminate parse, triggers, app_output, G1/G2/G3 views.

ZC-WISH-004/005/009/011/012 — base-5 wire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

_CONFIDENCE = frozenset({"high", "med", "low"})
_G2_UI_FORBIDDEN = frozenset({
    "wish_i_knew",
    "jail_break_attempt",
    "subject_confidence",
    "data_gaps",
    "business_rules_triggers",
    "app_output",
    "hooks_jailbreak_score",
})


@dataclass
class LayerA:
    """Parsed terminate / return bag."""

    summary: str = ""
    query_decomposition: Optional[dict] = None
    decomposition: Optional[dict] = None
    confidence: Optional[str] = None
    policy_action: Optional[str] = None
    business_rules_triggers: dict[str, bool] = field(default_factory=dict)
    app_output: Optional[dict] = None
    jail_break_attempt: Optional[float] = None
    wish_i_knew: Optional[list] = None
    data_gaps: Optional[list] = None
    entity_refs: Any = None
    node_refs: Any = None
    provenance: Any = None
    raw: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_triggers(
    raw: Any,
    *,
    rule_ids: Sequence[str] | None = None,
    allow_array: bool = True,
) -> tuple[dict[str, bool], list[str]]:
    """Sparse object {id: bool}; missing ⇒ false. Dual-read array ≤1 release."""
    warnings: list[str] = []
    if raw is None:
        return {}, warnings
    if isinstance(raw, dict):
        return {str(k): bool(v) for k, v in raw.items()}, warnings
    if isinstance(raw, list):
        if not allow_array:
            warnings.append(
                "business_rules_triggers array rejected (allow_array_triggers=False)"
            )
            return {}, warnings
        if not rule_ids:
            warnings.append(
                "business_rules_triggers array without rule_ids mapping; ignored"
            )
            return {}, warnings
        out: dict[str, bool] = {}
        for i, rid in enumerate(rule_ids):
            out[str(rid)] = bool(raw[i]) if i < len(raw) else False
        warnings.append("business_rules_triggers dual-read from array (deprecated)")
        return out, warnings
    warnings.append(
        f"business_rules_triggers ignored (type {type(raw).__name__})"
    )
    return {}, warnings


def _type_name(t: str) -> str:
    return (t or "string").strip().lower()


def _value_matches_type(val: Any, type_name: str) -> bool:
    tn = _type_name(type_name)
    if tn in ("string", "str"):
        return isinstance(val, str)
    if tn in ("number", "float"):
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if tn in ("integer", "int"):
        return isinstance(val, int) and not isinstance(val, bool)
    if tn in ("boolean", "bool"):
        return isinstance(val, bool)
    if tn in ("object", "dict"):
        return isinstance(val, dict)
    if tn in ("array", "list"):
        return isinstance(val, list)
    if tn == "null":
        return val is None
    return True  # unknown types: permissive


def validate_app_output(
    app_output: Any,
    fields_spec: Mapping[str, Any] | None,
    *,
    on_error: str = "strip",
) -> tuple[Optional[dict], list[str]]:
    """Type-check app_output values against output_request.app.fields."""
    errors: list[str] = []
    if fields_spec is None:
        if app_output in (None, {}):
            return None if app_output is None else {}, errors
        # no spec — keep as object if dict
        if isinstance(app_output, dict):
            return dict(app_output), errors
        errors.append("app_output present but no output_request.app.fields")
        return ({} if on_error == "strip" else None), errors

    if app_output is None:
        return None, errors
    if not isinstance(app_output, dict):
        errors.append(f"app_output must be object, got {type(app_output).__name__}")
        return ({} if on_error == "strip" else None), errors

    out: dict = {}
    for name, spec in fields_spec.items():
        if not isinstance(spec, dict):
            continue
        if name not in app_output:
            continue
        val = app_output[name]
        tname = spec.get("type") or "string"
        if _value_matches_type(val, str(tname)):
            out[name] = val
        else:
            msg = (
                f"app_output.{name} type mismatch: expected {tname}, "
                f"got {type(val).__name__}"
            )
            errors.append(msg)
            if on_error != "strip":
                return None, errors
    # drop unknown keys silently (values-only bag; no second summary essay)
    return out, errors


def parse_layer_a(
    return_args: Any,
    *,
    rule_ids: Sequence[str] | None = None,
    allow_array_triggers: bool = True,
    output_request: Mapping[str, Any] | None = None,
    app_output_on_error: str = "strip",
) -> LayerA:
    """Parse and validate terminate payload (required four + G3)."""
    layer = LayerA(raw=dict(return_args) if isinstance(return_args, dict) else {})
    if not isinstance(return_args, dict):
        layer.errors.append("return payload is not an object")
        return layer

    summary = return_args.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        layer.errors.append("required field summary missing or empty")
    else:
        layer.summary = summary.strip()

    qd = return_args.get("query_decomposition")
    if not isinstance(qd, dict):
        layer.errors.append("required field query_decomposition must be an object")
    else:
        layer.query_decomposition = qd

    decomp = return_args.get("decomposition")
    if not isinstance(decomp, dict):
        # legacy alias
        decomp = return_args.get("query_understanding")
    if not isinstance(decomp, dict):
        layer.errors.append("required field decomposition must be an object")
    else:
        layer.decomposition = decomp

    conf = return_args.get("confidence")
    if not isinstance(conf, str) or conf not in _CONFIDENCE:
        layer.errors.append(
            "required field confidence must be one of high|med|low"
        )
    else:
        layer.confidence = conf

    pa = return_args.get("policy_action")
    if isinstance(pa, str) and pa.strip():
        layer.policy_action = pa.strip()

    triggers, tw = normalize_triggers(
        return_args.get("business_rules_triggers"),
        rule_ids=rule_ids,
        allow_array=allow_array_triggers,
    )
    layer.business_rules_triggers = triggers
    layer.warnings.extend(tw)

    jba = return_args.get("jail_break_attempt")
    if isinstance(jba, (int, float)) and not isinstance(jba, bool):
        layer.jail_break_attempt = float(jba)

    wik = return_args.get("wish_i_knew")
    if isinstance(wik, list):
        layer.wish_i_knew = wik
    elif wik is not None:
        layer.warnings.append("wish_i_knew ignored (expected array of objects)")

    dg = return_args.get("data_gaps")
    if isinstance(dg, list):
        layer.data_gaps = dg

    for key in ("entity_refs", "node_refs", "provenance"):
        if key in return_args:
            setattr(layer, key, return_args.get(key))

    fields_spec = None
    if isinstance(output_request, dict):
        app = output_request.get("app")
        if isinstance(app, dict) and isinstance(app.get("fields"), dict):
            fields_spec = app["fields"]

    app_out, app_errs = validate_app_output(
        return_args.get("app_output"),
        fields_spec,
        on_error=app_output_on_error,
    )
    layer.app_output = app_out
    if app_errs:
        if app_output_on_error == "fail":
            layer.errors.extend(app_errs)
        else:
            layer.warnings.extend(app_errs)

    return layer


def ui_view(layer: LayerA, *, ui_text: str | None = None) -> dict:
    """G1 user-facing view — never G2 admin scores / wish_i_knew."""
    text = ui_text if ui_text is not None else layer.summary
    out = {
        "summary": text,
        "confidence": layer.confidence,
        "policy_action": layer.policy_action,
    }
    # belt-and-suspenders: strip any forbidden keys if callers merge wrong
    for k in _G2_UI_FORBIDDEN:
        out.pop(k, None)
    return out


def artifacts_view(
    layer: LayerA,
    *,
    hooks_jailbreak_score: float | None = None,
    policy: str | None = None,
    flags: Mapping[str, bool] | None = None,
) -> dict:
    """Full Layer A + G2/G3 for artifacts / metrics — not chat UI."""
    return {
        "summary": layer.summary,
        "query_decomposition": layer.query_decomposition,
        "decomposition": layer.decomposition,
        "confidence": layer.confidence,
        "policy_action": layer.policy_action,
        "business_rules_triggers": dict(layer.business_rules_triggers),
        "app_output": layer.app_output,
        "jail_break_attempt": layer.jail_break_attempt,
        "hooks_jailbreak_score": hooks_jailbreak_score,
        "wish_i_knew": layer.wish_i_knew,
        "data_gaps": layer.data_gaps,
        "entity_refs": layer.entity_refs,
        "node_refs": layer.node_refs,
        "provenance": layer.provenance,
        "policy": policy,
        "flags": dict(flags or {}),
        "errors": list(layer.errors),
        "warnings": list(layer.warnings),
        "raw": layer.raw,
    }
