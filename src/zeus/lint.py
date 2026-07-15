"""Static conflict linter for chat_request catalogs (ZC-35).

Read-only diagnostics over the **open** (hash-excluded) surface of a
standardized V2 chat_request. Never rewrites contract-locked content.

Contract-locked (hashed — do not "fix" by rewriting)::

    instructions.*, masq, verbs / tools, messages[*].content
    (except content after ## SCOPE BRIEF / ## MINI-SCHEMA)

Open / advisory (hash-excluded — primary lint target)::

    entire guidance tree (injections.business_logic, optimal_paths, …),
    contract, metadata, _* keys, runtime brief / post-brief injects

Usage::

    from zeus_client import lint_chat_request
    report = lint_chat_request(chat_req)
    print(report.conflict_score, report.severity, report.findings)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Iterable, Optional

from zeus_client.contract_hash import HASH_EXCLUDED_ROOTS, LOCKED_POINTERS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCKED_PATHS_NOTE = (
    "Locked (hashed) content is never rewritten by this linter. "
    "Findings target open/hash-excluded surfaces only "
    f"({', '.join(HASH_EXCLUDED_ROOTS)})."
)

SEVERITY_WEIGHTS = {
    "high": 25,
    "medium": 10,
    "low": 3,
}

# Modality markers for free-text conflict heuristics
_ALWAYS = re.compile(
    r"\b(?:always|must|must\s+always|only|prefer|preferred|should\s+always|"
    r"require|required|insist)\b",
    re.I,
)
_NEVER = re.compile(
    r"\b(?:never|must\s+not|mustn't|do\s+not|don't|avoid|forbid|forbidden|"
    r"prohibit|prohibited|disallow|no\s+longer)\b",
    re.I,
)
_PREFER = re.compile(r"\b(?:prefer|preferred|use|favor|choose)\b", re.I)
_TOOL_TOKEN = re.compile(
    r"\b(find|search|get|describe|traverse|analyze|project|pipeline|enrich|"
    r"order|set|return|explain)\b",
    re.I,
)
_ENTITYISH = re.compile(r"\b([A-Z][a-zA-Z0-9_]{2,})\b")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleAtom:
    """One open rule / guidance fragment with a JSON path."""

    id: str
    path: str
    kind: str  # business_logic | optimal_path | output_schema
    text: str
    structured: Optional[dict] = None
    locked: bool = False


@dataclass(frozen=True)
class Finding:
    """One conflict or structural issue."""

    check_id: str
    severity: str  # high | medium | low
    message: str
    path_a: str
    path_b: Optional[str] = None
    rule_a: Optional[str] = None
    rule_b: Optional[str] = None


@dataclass
class ConflictReport:
    """Result of lint_chat_request."""

    conflict_score: int
    severity: str  # none | low | medium | high
    finding_count: int
    findings: list[Finding] = field(default_factory=list)
    open_rule_count: int = 0
    locked_paths_note: str = LOCKED_PATHS_NOTE
    hash_excluded_roots: list[str] = field(
        default_factory=lambda: list(HASH_EXCLUDED_ROOTS)
    )
    locked_pointers: list[str] = field(
        default_factory=lambda: list(LOCKED_POINTERS)
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def summary_line(self) -> str:
        return (
            f"catalog_lint: score={self.conflict_score} severity={self.severity} "
            f"findings={self.finding_count} open_rules={self.open_rule_count}"
        )

    def format_text(self) -> str:
        lines = [
            "=== chat_request conflict lint ===",
            self.summary_line(),
            self.locked_paths_note,
            f"hash_excluded_roots: {', '.join(self.hash_excluded_roots)}",
            f"locked_pointers: {', '.join(self.locked_pointers)}",
            "",
        ]
        if not self.findings:
            lines.append("No findings.")
            return "\n".join(lines)
        for i, f in enumerate(self.findings, 1):
            pair = f" vs {f.path_b}" if f.path_b else ""
            lines.append(f"{i}. [{f.severity}] {f.check_id}: {f.message}")
            lines.append(f"   path: {f.path_a}{pair}")
            if f.rule_a:
                lines.append(f"   rule_a: {f.rule_a[:200]}")
            if f.rule_b:
                lines.append(f"   rule_b: {f.rule_b[:200]}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def inventory_open_rules(chat_req: dict) -> list[RuleAtom]:
    """Extract open (hash-excluded) rule atoms from a chat_request."""
    if not isinstance(chat_req, dict):
        return []
    atoms: list[RuleAtom] = []
    guidance = chat_req.get("guidance") or {}
    if not isinstance(guidance, dict):
        return atoms

    injections = guidance.get("injections") or {}
    if isinstance(injections, dict):
        bl = injections.get("business_logic") or []
        if isinstance(bl, list):
            for i, raw in enumerate(bl):
                atom = _business_logic_atom(raw, i)
                if atom:
                    atoms.append(atom)
        schema = injections.get("output_schema")
        if schema:
            atoms.append(RuleAtom(
                id="output_schema",
                path="guidance.injections.output_schema",
                kind="output_schema",
                text=_schema_text(schema),
                structured={"output_schema": schema} if isinstance(schema, dict) else None,
            ))

    paths = guidance.get("optimal_paths") or []
    if isinstance(paths, list):
        for i, op in enumerate(paths):
            if not isinstance(op, dict):
                continue
            text_parts = [
                str(op.get("when_to_use") or ""),
                str(op.get("description") or ""),
                str(op.get("intent") or ""),
                str(op.get("notes") or ""),
            ]
            pipeline = op.get("pipeline") or []
            verbs = []
            if isinstance(pipeline, list):
                for step in pipeline:
                    if isinstance(step, dict) and step.get("verb"):
                        verbs.append(str(step["verb"]))
            text = " | ".join(p for p in text_parts if p)
            if verbs:
                text = (text + " | verbs: " + " -> ".join(verbs)).strip(" |")
            atoms.append(RuleAtom(
                id=str(op.get("id") or f"op{i + 1}"),
                path=f"guidance.optimal_paths[{i}]",
                kind="optimal_path",
                text=text,
                structured=op,
            ))

    return atoms


def _business_logic_atom(raw: Any, index: int) -> Optional[RuleAtom]:
    if isinstance(raw, str):
        return RuleAtom(
            id=f"r{index + 1}",
            path=f"guidance.injections.business_logic[{index}]",
            kind="business_logic",
            text=raw,
            structured={"rule": raw},
        )
    if isinstance(raw, dict):
        rid = str(raw.get("id") or f"r{index + 1}")
        text = str(raw.get("rule") or raw.get("text") or "")
        if not text:
            text = str({k: raw[k] for k in raw if k not in ("id",)})
        return RuleAtom(
            id=rid,
            path=f"guidance.injections.business_logic[{index}]",
            kind="business_logic",
            text=text,
            structured=dict(raw),
        )
    return None


def _schema_text(schema: Any) -> str:
    if isinstance(schema, dict):
        try:
            import json
            return json.dumps(schema, sort_keys=True)[:500]
        except Exception:
            return str(schema)[:500]
    return str(schema)[:500]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_findings(findings: Iterable[Finding]) -> tuple[int, str]:
    """Return (conflict_score 0–100, severity band)."""
    findings = list(findings)
    if not findings:
        return 0, "none"
    total = 0
    for f in findings:
        total += SEVERITY_WEIGHTS.get(f.severity, 3)
    score = min(100, total)
    if score >= 50:
        band = "high"
    elif score >= 25:
        band = "medium"
    elif score >= 1:
        band = "low"
    else:
        band = "none"
    return score, band


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------

def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _tools_in_text(text: str) -> set[str]:
    return {m.group(1).lower() for m in _TOOL_TOKEN.finditer(text or "")}


def _shared_tokens(a: str, b: str, min_len: int = 4) -> set[str]:
    """Content words shared by two strings (excluding modality noise)."""
    stop = {
        "always", "never", "must", "should", "prefer", "preferred", "avoid",
        "use", "using", "the", "and", "for", "with", "from", "that", "this",
        "when", "then", "only", "not", "dont", "don't", "entity", "type",
        "rule", "rules", "data", "query", "rows", "please", "will", "shall",
    }
    wa = {w for w in re.findall(r"[a-z0-9_]+", a.lower()) if len(w) >= min_len and w not in stop}
    wb = {w for w in re.findall(r"[a-z0-9_]+", b.lower()) if len(w) >= min_len and w not in stop}
    return wa & wb


def check_negation_pairs(atoms: list[RuleAtom]) -> list[Finding]:
    """always/must vs never/must-not over shared topic + tool."""
    findings: list[Finding] = []
    bl = [a for a in atoms if a.kind == "business_logic" and a.text]
    for a, b in combinations(bl, 2):
        a_pos, a_neg = bool(_ALWAYS.search(a.text)), bool(_NEVER.search(a.text))
        b_pos, b_neg = bool(_ALWAYS.search(b.text)), bool(_NEVER.search(b.text))
        # One positive modality, one negative
        if not ((a_pos and b_neg) or (a_neg and b_pos)):
            continue
        shared = _shared_tokens(a.text, b.text)
        tools_a, tools_b = _tools_in_text(a.text), _tools_in_text(b.text)
        tool_overlap = tools_a & tools_b
        # Require either shared content words or same tool mention
        if not shared and not tool_overlap:
            # Same entity_type in structured rules is enough
            ea = (a.structured or {}).get("entity_type")
            eb = (b.structured or {}).get("entity_type")
            if not (ea and eb and ea == eb):
                continue
        topic = ", ".join(sorted(tool_overlap or shared)[:6]) or "related topic"
        findings.append(Finding(
            check_id="negation_pair",
            severity="high",
            message=f"Opposing always/never (or prefer/avoid) modalities on {topic}",
            path_a=a.path,
            path_b=b.path,
            rule_a=a.text,
            rule_b=b.text,
        ))
    return findings


def check_exclusive_preferred_tools(atoms: list[RuleAtom]) -> list[Finding]:
    """Two open rules that prefer different tools for the same topic."""
    findings: list[Finding] = []
    candidates: list[tuple[RuleAtom, set[str], set[str]]] = []
    for a in atoms:
        if a.kind not in ("business_logic", "optimal_path") or not a.text:
            continue
        if not (_PREFER.search(a.text) or _ALWAYS.search(a.text) or a.kind == "optimal_path"):
            continue
        tools = _tools_in_text(a.text)
        # For optimal_path, first pipeline verb is the preferred entry
        if a.kind == "optimal_path" and a.structured:
            pipe = a.structured.get("pipeline") or []
            if isinstance(pipe, list) and pipe and isinstance(pipe[0], dict):
                v = pipe[0].get("verb")
                if v:
                    tools = {str(v).lower()} | tools
        if not tools:
            continue
        tokens = _shared_tokens(a.text, a.text)  # content tokens of this rule
        # Prefer content from when_to_use / description
        content = set(re.findall(r"[a-z0-9_]{4,}", a.text.lower()))
        candidates.append((a, tools, content))

    for (a, ta, ca), (b, tb, cb) in combinations(candidates, 2):
        if ta == tb:
            continue
        # Need some topical overlap (shared words) or same entity_type
        overlap = ca & cb
        ea = (a.structured or {}).get("entity_type")
        eb = (b.structured or {}).get("entity_type")
        same_et = ea and eb and ea == eb
        # optimal_paths: overlapping intent_pattern output / targets
        if a.kind == "optimal_path" and b.kind == "optimal_path":
            if _optimal_path_intent_overlap(a.structured or {}, b.structured or {}):
                findings.append(Finding(
                    check_id="exclusive_preferred_tools",
                    severity="medium",
                    message=(
                        f"Overlapping optimal_paths prefer different entry verbs: "
                        f"{sorted(ta)} vs {sorted(tb)}"
                    ),
                    path_a=a.path,
                    path_b=b.path,
                    rule_a=a.text,
                    rule_b=b.text,
                ))
                continue
        if not overlap and not same_et:
            continue
        if a.kind == "business_logic" and b.kind == "business_logic":
            if not (_PREFER.search(a.text) or _ALWAYS.search(a.text)):
                continue
            if not (_PREFER.search(b.text) or _ALWAYS.search(b.text)):
                continue
            findings.append(Finding(
                check_id="exclusive_preferred_tools",
                severity="high",
                message=(
                    f"Conflicting preferred tools: {sorted(ta)} vs {sorted(tb)}"
                ),
                path_a=a.path,
                path_b=b.path,
                rule_a=a.text,
                rule_b=b.text,
            ))
    return findings


def _optimal_path_intent_overlap(a: dict, b: dict) -> bool:
    pa = a.get("intent_pattern") or {}
    pb = b.get("intent_pattern") or {}
    if not isinstance(pa, dict) or not isinstance(pb, dict):
        # Fall back to when_to_use token overlap
        return bool(_shared_tokens(str(a.get("when_to_use") or ""), str(b.get("when_to_use") or "")))
    out_a, out_b = pa.get("output"), pb.get("output")
    if out_a and out_b and out_a != out_b:
        return False
    ta = set(pa.get("target_entity_types") or [])
    tb = set(pb.get("target_entity_types") or [])
    if ta and tb:
        if "*" in ta or "*" in tb or ta & tb:
            return True
        return False
    return bool(_shared_tokens(str(a.get("when_to_use") or a.get("intent") or ""),
                               str(b.get("when_to_use") or b.get("intent") or "")))


def check_structured_predicate_clash(atoms: list[RuleAtom]) -> list[Finding]:
    """deny_when vs require on same entity that cannot both hold."""
    findings: list[Finding] = []
    bl = [a for a in atoms if a.kind == "business_logic" and a.structured]
    for a, b in combinations(bl, 2):
        sa, sb = a.structured or {}, b.structured or {}
        ea, eb = sa.get("entity_type"), sb.get("entity_type")
        if ea and eb and ea != eb:
            continue
        deny_a, req_a = sa.get("deny_when"), sa.get("require")
        deny_b, req_b = sb.get("deny_when"), sb.get("require")
        # Cross pairs: deny_when of one vs require of the other
        for label, pred_deny, pred_req, path_d, path_r, text_d, text_r in (
            ("a_deny_b_req", deny_a, req_b, a.path, b.path, a.text, b.text),
            ("b_deny_a_req", deny_b, req_a, b.path, a.path, b.text, a.text),
        ):
            if not isinstance(pred_deny, dict) or not isinstance(pred_req, dict):
                continue
            if _predicates_conflict(pred_deny, pred_req):
                findings.append(Finding(
                    check_id="structured_predicate_clash",
                    severity="high",
                    message=(
                        f"deny_when and require on overlapping fields are incompatible"
                        f"{f' for entity_type={ea or eb}' if (ea or eb) else ''}"
                    ),
                    path_a=path_d,
                    path_b=path_r,
                    rule_a=text_d,
                    rule_b=text_r,
                ))
        # Two deny_when that encode opposite equality on same field
        if isinstance(deny_a, dict) and isinstance(deny_b, dict):
            if _deny_pair_impossible(deny_a, deny_b):
                findings.append(Finding(
                    check_id="structured_predicate_clash",
                    severity="medium",
                    message="Paired deny_when predicates cover contradictory equalities",
                    path_a=a.path,
                    path_b=b.path,
                    rule_a=a.text,
                    rule_b=b.text,
                ))
    return findings


def _predicates_conflict(deny: dict, require: dict) -> bool:
    """True if a row matching `require` would always match `deny` (impossible compliance)."""
    for field, req_cond in require.items():
        if field not in deny:
            continue
        deny_cond = deny[field]
        if _cond_implies_match(req_cond, deny_cond):
            return True
    return False


def _cond_implies_match(req_cond: Any, deny_cond: Any) -> bool:
    """Whether satisfying req_cond implies the deny_cond also matches."""
    # Equality-style: require state==CA and deny state==CA
    if not isinstance(req_cond, dict) and not isinstance(deny_cond, dict):
        return req_cond == deny_cond
    if not isinstance(req_cond, dict) and isinstance(deny_cond, dict):
        # require exact value; deny has ops
        return _value_matches_ops(req_cond, deny_cond)
    if isinstance(req_cond, dict) and not isinstance(deny_cond, dict):
        # require has ops; deny is equality — only if require forces that equality
        if set(req_cond.keys()) <= {"=="} and req_cond.get("==") == deny_cond:
            return True
        return False
    # both dicts of ops — simple interval / equality conflicts
    assert isinstance(req_cond, dict) and isinstance(deny_cond, dict)
    # If require says == X and deny says == X
    if "==" in req_cond and "==" in deny_cond and req_cond["=="] == deny_cond["=="]:
        return True
    if "==" in req_cond:
        return _value_matches_ops(req_cond["=="], deny_cond)
    # require >= N and deny > N-epsilon style: require abv >= 8, deny abv > 7
    try:
        if ">=" in req_cond and ">" in deny_cond:
            if float(req_cond[">="]) > float(deny_cond[">"]):
                return True
            if float(req_cond[">="]) == float(deny_cond[">"]):
                # require abv>=8, deny abv>7 → rows with abv>=8 match deny
                return True
        if ">" in req_cond and ">" in deny_cond:
            if float(req_cond[">"]) >= float(deny_cond[">"]):
                return True
        if ">=" in req_cond and ">=" in deny_cond:
            if float(req_cond[">="]) >= float(deny_cond[">="]):
                return True
    except (TypeError, ValueError):
        pass
    return False


def _value_matches_ops(value: Any, ops: dict) -> bool:
    try:
        for op, target in ops.items():
            if op == "==" and value != target:
                return False
            if op == "!=" and value == target:
                return False
            if op == ">" and not (value is not None and value > target):
                return False
            if op == ">=" and not (value is not None and value >= target):
                return False
            if op == "<" and not (value is not None and value < target):
                return False
            if op == "<=" and not (value is not None and value <= target):
                return False
            if op == "in" and value not in target:
                return False
        return True
    except TypeError:
        return False


def _deny_pair_impossible(d1: dict, d2: dict) -> bool:
    """Heuristic: two deny rules with opposite exact equalities on same sole field."""
    if set(d1.keys()) != set(d2.keys()):
        return False
    if len(d1) != 1:
        return False
    k = next(iter(d1))
    v1, v2 = d1[k], d2[k]
    if isinstance(v1, dict) or isinstance(v2, dict):
        return False
    return v1 != v2


def check_optimal_path_structure(
    atoms: list[RuleAtom],
    catalog_verbs: set[str],
) -> list[Finding]:
    """Pipeline shape issues: unknown verbs, missing as, return names verbs, too many steps."""
    findings: list[Finding] = []
    for a in atoms:
        if a.kind != "optimal_path" or not a.structured:
            continue
        op = a.structured
        pipeline = op.get("pipeline") or []
        if not isinstance(pipeline, list):
            continue
        if len(pipeline) > 8:
            findings.append(Finding(
                check_id="optimal_path_too_many_steps",
                severity="medium",
                message=f"optimal_path pipeline has {len(pipeline)} steps (max 8)",
                path_a=a.path,
                rule_a=a.text,
            ))
        step_as: list[str] = []
        for si, step in enumerate(pipeline):
            if not isinstance(step, dict):
                continue
            verb = step.get("verb")
            alias = step.get("as")
            step_path = f"{a.path}.pipeline[{si}]"
            if not alias:
                findings.append(Finding(
                    check_id="optimal_path_missing_as",
                    severity="medium",
                    message=f"pipeline step missing unique 'as' binding (verb={verb!r})",
                    path_a=step_path,
                    rule_a=a.text,
                ))
            else:
                step_as.append(str(alias))
            if verb and catalog_verbs and str(verb).lower() not in catalog_verbs:
                findings.append(Finding(
                    check_id="optimal_path_unknown_verb",
                    severity="medium",
                    message=f"pipeline verb {verb!r} not in catalog verbs {sorted(catalog_verbs)}",
                    path_a=step_path,
                    rule_a=a.text,
                ))
        ret = op.get("return") or []
        if isinstance(ret, list) and ret:
            as_set = set(step_as)
            verb_names = catalog_verbs or set()
            for rname in ret:
                rs = str(rname)
                if rs in as_set:
                    continue
                if rs.lower() in verb_names:
                    findings.append(Finding(
                        check_id="optimal_path_return_is_verb",
                        severity="medium",
                        message=(
                            f"return[] lists verb name {rs!r}; must list step 'as' bindings"
                        ),
                        path_a=f"{a.path}.return",
                        rule_a=a.text,
                    ))
                elif as_set:
                    findings.append(Finding(
                        check_id="optimal_path_unknown_return",
                        severity="medium",
                        message=f"return[] name {rs!r} is not a step 'as' binding {sorted(as_set)}",
                        path_a=f"{a.path}.return",
                        rule_a=a.text,
                    ))
    return findings


def check_duplicate_rules(atoms: list[RuleAtom]) -> list[Finding]:
    findings: list[Finding] = []
    bl = [a for a in atoms if a.kind == "business_logic"]
    seen_ids: dict[str, RuleAtom] = {}
    seen_text: dict[str, RuleAtom] = {}
    for a in bl:
        if a.id in seen_ids:
            prev = seen_ids[a.id]
            findings.append(Finding(
                check_id="duplicate_rule_id",
                severity="low",
                message=f"Duplicate business_logic id {a.id!r}",
                path_a=prev.path,
                path_b=a.path,
                rule_a=prev.text,
                rule_b=a.text,
            ))
        else:
            seen_ids[a.id] = a
        nt = _normalize_text(a.text)
        if nt and nt in seen_text:
            prev = seen_text[nt]
            findings.append(Finding(
                check_id="duplicate_rule_text",
                severity="low",
                message="Near-duplicate business_logic text",
                path_a=prev.path,
                path_b=a.path,
                rule_a=prev.text,
                rule_b=a.text,
            ))
        elif nt:
            seen_text[nt] = a
    return findings


def check_schema_orphans(atoms: list[RuleAtom], mini_schema: dict) -> list[Finding]:
    """entity_type / fields unknown vs MINI-SCHEMA (when present)."""
    ets = (mini_schema or {}).get("entity_types") or {}
    if not ets:
        return []
    findings: list[Finding] = []
    for a in atoms:
        if a.kind != "business_logic" or not a.structured:
            continue
        et = a.structured.get("entity_type")
        if not et:
            continue
        if et not in ets:
            findings.append(Finding(
                check_id="schema_unknown_entity",
                severity="medium",
                message=f"business rule entity_type {et!r} not in MINI-SCHEMA {sorted(ets)}",
                path_a=a.path,
                rule_a=a.text,
            ))
            continue
        known = (ets[et].get("fields") or {})
        bad = [f for f in (a.structured.get("fields") or []) if f not in known]
        if bad:
            findings.append(Finding(
                check_id="schema_unknown_fields",
                severity="medium",
                message=(
                    f"business rule for {et!r} references unknown field(s) {bad}; "
                    f"valid: {sorted(known)}"
                ),
                path_a=a.path,
                rule_a=a.text,
            ))
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _catalog_verb_names(chat_req: dict) -> set[str]:
    from zeus_client.zeus.catalog import tools_from_chat_request
    names: set[str] = set()
    for t in tools_from_chat_request(chat_req) or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        n = (fn or {}).get("name")
        if n:
            names.add(str(n).lower())
    return names


def lint_chat_request(
    chat_req: dict,
    *,
    include_structural: bool = True,
    include_schema: bool = True,
) -> ConflictReport:
    """Analyze a chat_request for conflicting open rules.

    Pure / read-only: does not mutate ``chat_req``. Contract-locked paths are
    never rewritten.

    Args:
        chat_req: Loaded chat_request document (dict).
        include_structural: Run optimal_paths pipeline shape checks.
        include_schema: Check business_logic entity/fields against MINI-SCHEMA
            when a brief is present.
    """
    # Work on a shallow guard: inventory never mutates, but be defensive.
    if not isinstance(chat_req, dict):
        return ConflictReport(
            conflict_score=0,
            severity="none",
            finding_count=0,
            findings=[],
            open_rule_count=0,
        )

    atoms = inventory_open_rules(chat_req)
    findings: list[Finding] = []
    findings.extend(check_negation_pairs(atoms))
    findings.extend(check_exclusive_preferred_tools(atoms))
    findings.extend(check_structured_predicate_clash(atoms))
    findings.extend(check_duplicate_rules(atoms))

    if include_structural:
        findings.extend(
            check_optimal_path_structure(atoms, _catalog_verb_names(chat_req))
        )

    if include_schema:
        try:
            from zeus_client.zeus.catalog import get_mini_schema
            mini = get_mini_schema(chat_req, values=False)
        except Exception:
            mini = {}
        findings.extend(check_schema_orphans(atoms, mini or {}))

    # Stable order: severity then check_id then path
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (sev_rank.get(f.severity, 9), f.check_id, f.path_a, f.path_b or ""))

    score, band = score_findings(findings)
    return ConflictReport(
        conflict_score=score,
        severity=band,
        finding_count=len(findings),
        findings=findings,
        open_rule_count=len(atoms),
        locked_paths_note=LOCKED_PATHS_NOTE,
        hash_excluded_roots=list(HASH_EXCLUDED_ROOTS),
        locked_pointers=list(LOCKED_POINTERS),
    )


def hash_policy_summary() -> dict[str, list[str]]:
    """Document locked vs open paths for debug UIs and CLI headers."""
    return {
        "hash_excluded_roots": list(HASH_EXCLUDED_ROOTS),
        "locked_pointers": list(LOCKED_POINTERS),
        "note": [
            LOCKED_PATHS_NOTE,
            "Open insert surface for operators/plugins: guidance.* "
            "(especially injections.business_logic and optimal_paths).",
        ],
    }
