"""Layer A terminate bag — base-5 / base-5.2 parse + validate (ZC-WISH floor).

Parses Zeus ``return`` / ``return_result`` args into a structured Layer A view:

* Required four: summary · query_decomposition · decomposition · confidence
* Object ``business_rules_triggers`` (sparse {id: bool}); optional ≤1-release
  dual-read of parallel arrays then normalize to object
* base-5.2 dual gaps: ``wish_i_knew`` (array of objects) + ``data_gaps``
* ``policy_action``, ``app_output``, ``synthetic`` for policy table / Helios

G2 fields never belong in chat UI — callers use :attr:`LayerABag.summary` (G1)
for user text and keep the rest on artifacts / metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# Layer A required four (BIBLE / COMPAT / Detective)
REQUIRED_FOUR = ("summary", "query_decomposition", "decomposition", "confidence")

# Confidence enum (pack soft enum)
_CONFIDENCE_OK = frozenset({"high", "med", "low", "medium", "HIGH", "MED", "LOW"})


@dataclass
class LayerABag:
    """Normalized terminate Layer A for Client policy / UI redaction / Helios."""

    # G1
    summary: str = ""
    # Required structural
    query_decomposition: Optional[dict] = None
    decomposition: Optional[dict] = None
    confidence: Optional[str] = None
    # G3 control
    policy_action: Optional[str] = None
    business_rules_triggers: dict[str, bool] = field(default_factory=dict)
    business_rules_triggers_present: bool = False
    app_output: Optional[dict] = None
    # G2 dual gaps (base-5.2)
    wish_i_knew: list[dict] = field(default_factory=list)
    wish_i_knew_flat: list[str] = field(default_factory=list)
    data_gaps: list[Any] = field(default_factory=list)
    data_gaps_present: bool = False
    # Observability
    synthetic: bool = False
    subject_confidence: Optional[float] = None
    jail_break_attempt: Optional[float] = None
    # Validation
    missing_required: list[str] = field(default_factory=list)
    shape_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def required_four_ok(self) -> bool:
        return not self.missing_required

    @property
    def shape_ok(self) -> bool:
        return not self.shape_errors

    def g1_answer(self, fallback: str = "") -> str:
        """User-facing text only — never dump G2/G3 into chat bubbles."""
        s = (self.summary or "").strip()
        return s if s else (fallback or "")


def _as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    return None


def _as_float(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def normalize_business_rules_triggers(
    raw: Any,
    *,
    dual_read_arrays: bool = True,
) -> tuple[dict[str, bool], bool, list[str]]:
    """Return (object_map, present, warnings).

    * Missing key → present=False, empty map
    * Object → sparse {str: bool}; non-bool values skipped
    * Array (transition only when dual_read_arrays) → positional flags as
      ``rule_N`` keys + warning (ZC-WISH-005 sunset path)
    """
    warnings: list[str] = []
    if raw is None:
        return {}, False, warnings
    if isinstance(raw, dict):
        out: dict[str, bool] = {}
        for k, v in raw.items():
            key = str(k).strip()
            if not key:
                continue
            b = _as_bool(v)
            if b is None:
                warnings.append(
                    f"layer_a: business_rules_triggers[{key!r}] not bool — skipped"
                )
                continue
            out[key] = b
        return out, True, warnings
    if isinstance(raw, list):
        if not dual_read_arrays:
            warnings.append(
                "layer_a: business_rules_triggers array rejected (dual-read disabled)"
            )
            return {}, True, warnings
        warnings.append(
            "layer_a: business_rules_triggers array dual-read — migrate to object {id: bool}"
        )
        out = {}
        for i, v in enumerate(raw):
            b = _as_bool(v)
            if b is None:
                continue
            out[f"rule_{i}"] = b
        return out, True, warnings
    warnings.append(
        f"layer_a: business_rules_triggers wrong type {type(raw).__name__} — dropped"
    )
    return {}, True, warnings


def normalize_wish_i_knew(raw: Any) -> tuple[list[dict], list[str], list[str]]:
    """Return (items, flat_strings, warnings).

    Accepts:
    * array of objects ``{what, kind?, why?, severity?}``
    * array of strings (flattened)
    * single string (legacy) → one item kind=message
    """
    warnings: list[str] = []
    items: list[dict] = []
    flat: list[str] = []

    if raw is None:
        return items, flat, warnings

    if isinstance(raw, str):
        s = raw.strip()
        if s:
            warnings.append("layer_a: wish_i_knew string dual-read — prefer array of objects")
            items.append({"what": s, "kind": "message"})
            flat.append(s)
        return items, flat, warnings

    if not isinstance(raw, list):
        warnings.append(f"layer_a: wish_i_knew wrong type {type(raw).__name__}")
        return items, flat, warnings

    for i, el in enumerate(raw[:3]):  # pack cap max 3
        if isinstance(el, str):
            s = el.strip()
            if s:
                items.append({"what": s, "kind": "message"})
                flat.append(s)
            continue
        if isinstance(el, dict):
            what = el.get("what")
            if not isinstance(what, str) or not what.strip():
                warnings.append(f"layer_a: wish_i_knew[{i}] missing what — skipped")
                continue
            item = {"what": what.strip()}
            for k in ("kind", "why", "severity"):
                v = el.get(k)
                if isinstance(v, str) and v.strip():
                    item[k] = v.strip()
            items.append(item)
            flat.append(what.strip())
            continue
        warnings.append(f"layer_a: wish_i_knew[{i}] not object/string — skipped")

    return items, flat, warnings


def normalize_data_gaps(raw: Any) -> tuple[list[Any], bool, list[str]]:
    """Return (list, present, warnings). Empty list still present=True if key was set."""
    warnings: list[str] = []
    if raw is None:
        return [], False, warnings
    if isinstance(raw, list):
        return list(raw), True, warnings
    warnings.append(f"layer_a: data_gaps wrong type {type(raw).__name__} — treated empty")
    return [], True, warnings


def parse_layer_a(
    payload: Optional[dict],
    *,
    dual_read_array_triggers: bool = True,
) -> LayerABag:
    """Parse a terminate args dict into :class:`LayerABag`."""
    bag = LayerABag()
    if not isinstance(payload, dict) or not payload:
        bag.missing_required = list(REQUIRED_FOUR)
        bag.warnings.append("layer_a: empty or missing return payload")
        return bag

    # --- summary (G1)
    summary = payload.get("summary")
    if isinstance(summary, str):
        bag.summary = summary.strip()
    elif summary is not None:
        bag.shape_errors.append("layer_a: summary must be string")

    # --- query_decomposition
    qd = payload.get("query_decomposition")
    if isinstance(qd, dict):
        bag.query_decomposition = qd
        if qd.get("synthetic") is True:
            bag.synthetic = True
    elif qd is not None:
        bag.shape_errors.append("layer_a: query_decomposition must be object")

    # --- decomposition (prose rationale)
    decomp = payload.get("decomposition")
    if isinstance(decomp, dict):
        bag.decomposition = decomp
    elif isinstance(decomp, str) and decomp.strip():
        # some models emit string — keep as soft object
        bag.decomposition = {"text": decomp.strip()}
        bag.warnings.append("layer_a: decomposition was string — wrapped as {text}")
    elif decomp is not None:
        bag.shape_errors.append("layer_a: decomposition must be object or string")

    # Also accept legacy query_understanding as QD fallback only
    if bag.query_decomposition is None:
        qu = payload.get("query_understanding")
        if isinstance(qu, dict):
            bag.query_decomposition = qu
            bag.warnings.append("layer_a: used query_understanding as query_decomposition")

    # decomposition from payload may also be under wrong key for older traces
    if bag.decomposition is None and isinstance(payload.get("decomposition"), dict):
        bag.decomposition = payload["decomposition"]

    # --- confidence
    conf = payload.get("confidence")
    if isinstance(conf, str) and conf.strip():
        bag.confidence = conf.strip()
        if conf.strip() not in _CONFIDENCE_OK and conf.strip().lower() not in {
            "high", "med", "medium", "low"
        }:
            bag.warnings.append(f"layer_a: confidence {conf!r} outside high|med|low")
    elif conf is not None:
        bag.shape_errors.append("layer_a: confidence must be string")

    # --- policy_action
    pa = payload.get("policy_action")
    if isinstance(pa, str) and pa.strip():
        bag.policy_action = pa.strip()
    elif pa is not None:
        bag.shape_errors.append("layer_a: policy_action must be string")

    # --- synthetic
    if payload.get("synthetic") is True:
        bag.synthetic = True

    # --- triggers
    if "business_rules_triggers" in payload:
        m, present, w = normalize_business_rules_triggers(
            payload.get("business_rules_triggers"),
            dual_read_arrays=dual_read_array_triggers,
        )
        bag.business_rules_triggers = m
        bag.business_rules_triggers_present = present
        bag.warnings.extend(w)
        if present and isinstance(payload.get("business_rules_triggers"), list):
            # dual-read path already warned
            pass

    # --- wish_i_knew
    if "wish_i_knew" in payload:
        items, flat, w = normalize_wish_i_knew(payload.get("wish_i_knew"))
        bag.wish_i_knew = items
        bag.wish_i_knew_flat = flat
        bag.warnings.extend(w)

    # --- data_gaps
    if "data_gaps" in payload:
        gaps, present, w = normalize_data_gaps(payload.get("data_gaps"))
        bag.data_gaps = gaps
        bag.data_gaps_present = present
        bag.warnings.extend(w)

    # --- app_output
    ao = payload.get("app_output")
    if isinstance(ao, dict):
        bag.app_output = ao
    elif ao is not None:
        bag.shape_errors.append("layer_a: app_output must be object")

    # --- scores
    bag.subject_confidence = _as_float(payload.get("subject_confidence"))
    bag.jail_break_attempt = _as_float(payload.get("jail_break_attempt"))

    # --- required four
    missing: list[str] = []
    if not bag.summary:
        missing.append("summary")
    if bag.query_decomposition is None:
        missing.append("query_decomposition")
    if bag.decomposition is None:
        missing.append("decomposition")
    if not bag.confidence:
        missing.append("confidence")
    bag.missing_required = missing

    return bag


def parse_layer_a_from_trace(
    trace: dict,
    *,
    dual_read_array_triggers: bool = True,
) -> LayerABag:
    """Find last return/return_result args in a Client agent trace and parse."""
    payload: dict = {}
    for step in reversed(trace.get("steps") or []):
        if not isinstance(step, dict):
            continue
        if step.get("type") in ("return", "return_result"):
            args = step.get("args")
            if isinstance(args, dict):
                payload = args
                break
    return parse_layer_a(payload, dual_read_array_triggers=dual_read_array_triggers)
