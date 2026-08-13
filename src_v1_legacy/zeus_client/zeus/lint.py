"""Static conflict linter for chat_request catalogs (ZC-35 V1 + ZC-36 V2).

Read-only diagnostics over open (hash-excluded) guidance and open-vs-locked
checks. Never rewrites contract-locked content.

**V1 (ZC-35)** — soft / advisory heuristics (always/never NL, duplicates,
optimal_paths hygiene) plus structured ``deny_when``/``require`` clashes.

**V2 (ZC-36)** — structured open-rule effects (``prefer_tool`` / ``forbid_tool``
…), deterministic hard conflict matrix, open-vs-locked checks, assemble-time
cache, and config knobs (``mode``, ``hard_conflicts``, ``soft_nl``, ``fail_on``).

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

    # Assemble-time with cache (agent / session start):
    report = lint_catalog_assembled(chat_req)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Iterable, Optional

from zeus_client.contract_hash import (
    HASH_EXCLUDED_ROOTS,
    LOCKED_POINTERS,
    compute_contract_hash,
    extract_stamped_hash,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LINT_VERSION = "v2"

LOCKED_PATHS_NOTE = (
    "Locked (hashed) content is never rewritten by this linter. "
    "Findings target open/hash-excluded surfaces and open-vs-locked oppositions "
    f"({', '.join(HASH_EXCLUDED_ROOTS)})."
)

SEVERITY_WEIGHTS = {
    "high": 25,
    "medium": 10,
    "low": 3,
}

# Structured open-rule effects (source of truth for hard conflicts).
# Prefer/forbid/require/allow over tools are first-class; prose remains rationale.
STRUCTURED_EFFECTS = frozenset({
    "prefer_tool",
    "forbid_tool",
    "require_tool",
    "allow_tool",
})

# Opposing effect pairs in the same (tool × when) space → hard conflict.
_OPPOSING_EFFECTS: frozenset[tuple[str, str]] = frozenset({
    ("prefer_tool", "forbid_tool"),
    ("forbid_tool", "prefer_tool"),
    ("require_tool", "forbid_tool"),
    ("forbid_tool", "require_tool"),
    ("allow_tool", "forbid_tool"),
    ("forbid_tool", "allow_tool"),
})

# Provenance kind vocabulary (advisory documentation; free-form still accepted).
PROVENANCE_SOURCES = frozenset({"plugin", "operator", "workbench", "import"})
PROVENANCE_KINDS = frozenset({"policy", "routing", "safety", "style", "path"})

# Modality markers for free-text conflict heuristics (soft layer only)
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
# Locked-side tool stance extraction (best-effort; incomplete by design).
_LOCKED_PREFER_TOOL = re.compile(
    r"\b(?:prefer|preferred|use|favor|choose|always\s+use|should\s+use|"
    r"must\s+use)\s+(?:the\s+)?([a-z_][a-z0-9_]*)\b",
    re.I,
)
_LOCKED_FORBID_TOOL = re.compile(
    r"\b(?:never|do\s+not|don't|forbid|avoid|must\s+not|mustn't)\s+"
    r"(?:use\s+)?(?:the\s+)?([a-z_][a-z0-9_]*)\b",
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
    # V2 structured open-rule fields (empty when prose-only)
    effect: Optional[str] = None
    tool: Optional[str] = None
    when: Optional[dict] = None
    priority: Optional[int] = None
    provenance: Optional[dict] = None  # source, kind, plugin, …


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
    # V2 classification
    layer: str = "soft"  # hard | soft | open_vs_locked
    confidence: str = "medium"  # high | medium | low
    rule_id_a: Optional[str] = None
    rule_id_b: Optional[str] = None


@dataclass(frozen=True)
class CatalogLintConfig:
    """Knobs for catalog lint (guidance.catalog_lint + env overrides).

    mode:
      off      — do not run (library API still callable explicitly)
      assemble — run once per assembled catalog (cache); agent attaches summary
      debug    — like assemble + full report on agent trace
      ci       — full checks; CLI may fail on hard
    """

    mode: str = "off"  # off | assemble | debug | ci
    hard_conflicts: bool = True
    soft_nl: bool = True
    open_vs_locked: bool = True
    deep_llm: bool = False  # reserved; never default-on
    fail_on: str = "none"  # none | hard | high | medium | low
    include_structural: bool = True
    include_schema: bool = True

    def should_run_in_agent(self) -> bool:
        return self.mode in ("assemble", "debug", "ci")

    def attach_full_report_to_trace(self) -> bool:
        return self.mode in ("debug", "ci")


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
    # V2 fields
    lint_version: str = LINT_VERSION
    hard_finding_count: int = 0
    soft_finding_count: int = 0
    open_vs_locked_count: int = 0
    structured_rule_count: int = 0
    cache_key: Optional[str] = None
    mode: str = "assemble"
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        return (
            f"catalog_lint: version={self.lint_version} score={self.conflict_score} "
            f"severity={self.severity} findings={self.finding_count} "
            f"hard={self.hard_finding_count} soft={self.soft_finding_count} "
            f"open_vs_locked={self.open_vs_locked_count} "
            f"open_rules={self.open_rule_count}"
            + (f" cached=1" if self.from_cache else "")
        )

    def hard_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.layer == "hard"]

    def soft_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.layer == "soft"]

    def open_vs_locked_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.layer == "open_vs_locked"]

    def meets_fail_on(self, fail_on: str) -> bool:
        """True when report should fail CI / CLI for the given policy."""
        fo = (fail_on or "none").lower()
        if fo in ("", "none", "off"):
            return False
        if fo == "hard":
            return self.hard_finding_count > 0 or self.open_vs_locked_count > 0
        sev_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return sev_rank.get(self.severity, 0) >= sev_rank.get(fo, 99)

    def format_text(self) -> str:
        lines = [
            f"=== chat_request conflict lint ({self.lint_version}) ===",
            self.summary_line(),
            self.locked_paths_note,
            f"hash_excluded_roots: {', '.join(self.hash_excluded_roots)}",
            f"locked_pointers: {', '.join(self.locked_pointers)}",
            f"hard={self.hard_finding_count} soft={self.soft_finding_count} "
            f"open_vs_locked={self.open_vs_locked_count} "
            f"structured_rules={self.structured_rule_count}",
            "",
        ]
        if not self.findings:
            lines.append("No findings.")
            return "\n".join(lines)
        for i, f in enumerate(self.findings, 1):
            pair = f" vs {f.path_b}" if f.path_b else ""
            conf = f" conf={f.confidence}" if f.layer == "soft" else ""
            lines.append(
                f"{i}. [{f.severity}/{f.layer}{conf}] {f.check_id}: {f.message}"
            )
            lines.append(f"   path: {f.path_a}{pair}")
            if f.rule_id_a or f.rule_id_b:
                ids = " / ".join(
                    x for x in (f.rule_id_a, f.rule_id_b) if x
                )
                lines.append(f"   rule_ids: {ids}")
            if f.rule_a:
                lines.append(f"   rule_a: {f.rule_a[:200]}")
            if f.rule_b:
                lines.append(f"   rule_b: {f.rule_b[:200]}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def resolve_lint_config(
    chat_req: Optional[dict] = None,
    *,
    overrides: Optional[dict] = None,
) -> CatalogLintConfig:
    """Resolve catalog_lint config from guidance + env + explicit overrides.

    Precedence (later wins for provided keys): defaults → env →
    ``guidance.catalog_lint`` → overrides.
    """
    cfg = CatalogLintConfig()
    # Env
    env_mode = (os.environ.get("ZEUS_CATALOG_LINT_MODE") or "").strip().lower()
    if env_mode in ("off", "assemble", "debug", "ci"):
        cfg = CatalogLintConfig(mode=env_mode)
    env_fail = (os.environ.get("ZEUS_CATALOG_LINT_FAIL_ON") or "").strip().lower()
    if env_fail:
        cfg = CatalogLintConfig(
            mode=cfg.mode,
            hard_conflicts=cfg.hard_conflicts,
            soft_nl=cfg.soft_nl,
            open_vs_locked=cfg.open_vs_locked,
            deep_llm=cfg.deep_llm,
            fail_on=env_fail,
            include_structural=cfg.include_structural,
            include_schema=cfg.include_schema,
        )

    raw: dict[str, Any] = {}
    if isinstance(chat_req, dict):
        guidance = chat_req.get("guidance") or {}
        if isinstance(guidance, dict):
            cl = guidance.get("catalog_lint")
            if isinstance(cl, dict):
                raw.update(cl)
            # V1 signal: guidance.debug implies debug mode when mode unset
            if not raw.get("mode") and bool(guidance.get("debug")):
                raw.setdefault("mode", "debug")
    if overrides:
        raw.update({k: v for k, v in overrides.items() if v is not None})

    def _bool(v: Any, default: bool) -> bool:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    mode = str(raw.get("mode", cfg.mode) or "off").strip().lower()
    if mode not in ("off", "assemble", "debug", "ci"):
        mode = "off"
    fail_on = str(raw.get("fail_on", cfg.fail_on) or "none").strip().lower()
    return CatalogLintConfig(
        mode=mode,
        hard_conflicts=_bool(raw.get("hard_conflicts"), cfg.hard_conflicts),
        soft_nl=_bool(raw.get("soft_nl"), cfg.soft_nl),
        open_vs_locked=_bool(raw.get("open_vs_locked"), cfg.open_vs_locked),
        deep_llm=_bool(raw.get("deep_llm"), False),  # never default on
        fail_on=fail_on,
        include_structural=_bool(raw.get("include_structural"), cfg.include_structural),
        include_schema=_bool(raw.get("include_schema"), cfg.include_schema),
    )


# ---------------------------------------------------------------------------
# Cache (assemble-time)
# ---------------------------------------------------------------------------

_LINT_CACHE: dict[str, ConflictReport] = {}
_LINT_CACHE_LOCK = threading.Lock()
_LINT_CACHE_MAX = 64


def clear_lint_cache() -> None:
    """Drop all cached assemble-time lint reports (tests / hot reload)."""
    with _LINT_CACHE_LOCK:
        _LINT_CACHE.clear()


def open_rules_fingerprint(chat_req: dict) -> str:
    """Stable hash of open (hash-excluded) rule material for cache keys."""
    if not isinstance(chat_req, dict):
        return "empty"
    guidance = chat_req.get("guidance") or {}
    # Only material that affects lint findings
    payload = {
        "injections": (guidance.get("injections") if isinstance(guidance, dict) else None),
        "optimal_paths": (guidance.get("optimal_paths") if isinstance(guidance, dict) else None),
        "catalog_lint": (guidance.get("catalog_lint") if isinstance(guidance, dict) else None),
    }
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def catalog_lint_cache_key(
    chat_req: dict,
    *,
    config: Optional[CatalogLintConfig] = None,
) -> str:
    """Cache key = locked contract fingerprint + open rules hash + config flags."""
    cfg = config or resolve_lint_config(chat_req)
    try:
        locked = extract_stamped_hash(chat_req) or compute_contract_hash(chat_req)
    except Exception:
        locked = "unknown"
    open_fp = open_rules_fingerprint(chat_req)
    flags = (
        f"h={int(cfg.hard_conflicts)}s={int(cfg.soft_nl)}"
        f"o={int(cfg.open_vs_locked)}st={int(cfg.include_structural)}"
        f"sc={int(cfg.include_schema)}"
    )
    return f"{locked}|{open_fp}|{flags}"


def lint_catalog_assembled(
    chat_req: dict,
    *,
    config: Optional[CatalogLintConfig] = None,
    use_cache: bool = True,
) -> ConflictReport:
    """Assemble-time lint with optional cache (once per catalog fingerprint).

    Preferred entry for agent session start / catalog load. Does not mutate
    ``chat_req``. Never blocks the caller — always returns a report.
    """
    cfg = config or resolve_lint_config(chat_req)
    if cfg.mode == "off":
        return ConflictReport(
            conflict_score=0,
            severity="none",
            finding_count=0,
            findings=[],
            open_rule_count=0,
            mode="off",
            lint_version=LINT_VERSION,
        )

    key = catalog_lint_cache_key(chat_req, config=cfg)
    if use_cache:
        with _LINT_CACHE_LOCK:
            hit = _LINT_CACHE.get(key)
            if hit is not None:
                # Return a shallow copy with from_cache flag
                cached = ConflictReport(
                    conflict_score=hit.conflict_score,
                    severity=hit.severity,
                    finding_count=hit.finding_count,
                    findings=list(hit.findings),
                    open_rule_count=hit.open_rule_count,
                    locked_paths_note=hit.locked_paths_note,
                    hash_excluded_roots=list(hit.hash_excluded_roots),
                    locked_pointers=list(hit.locked_pointers),
                    lint_version=hit.lint_version,
                    hard_finding_count=hit.hard_finding_count,
                    soft_finding_count=hit.soft_finding_count,
                    open_vs_locked_count=hit.open_vs_locked_count,
                    structured_rule_count=hit.structured_rule_count,
                    cache_key=key,
                    mode=cfg.mode,
                    from_cache=True,
                )
                return cached

    report = lint_chat_request(
        chat_req,
        include_structural=cfg.include_structural,
        include_schema=cfg.include_schema,
        hard_conflicts=cfg.hard_conflicts,
        soft_nl=cfg.soft_nl,
        open_vs_locked=cfg.open_vs_locked,
        config=cfg,
    )
    report.cache_key = key
    report.mode = cfg.mode
    report.from_cache = False

    if use_cache:
        with _LINT_CACHE_LOCK:
            if len(_LINT_CACHE) >= _LINT_CACHE_MAX:
                # Drop an arbitrary oldest entry
                try:
                    _LINT_CACHE.pop(next(iter(_LINT_CACHE)))
                except StopIteration:
                    pass
            _LINT_CACHE[key] = report
    return report


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


def _parse_when(raw: dict) -> dict:
    """Normalize a structured ``when`` clause + top-level entity_type."""
    when: dict[str, Any] = {}
    explicit = raw.get("when")
    if isinstance(explicit, dict):
        when.update(explicit)
    et = raw.get("entity_type") or when.get("entity_type")
    if et:
        when["entity_type"] = et
    return when


def _parse_provenance(raw: dict, path: str, rid: str) -> dict:
    """Collect provenance fields for reports (Layer 0)."""
    prov: dict[str, Any] = {
        "id": rid,
        "path": path,
    }
    source = raw.get("source") or (raw.get("provenance") or {}).get("source")
    if source:
        prov["source"] = source
    kind = raw.get("kind") or (raw.get("provenance") or {}).get("kind")
    if kind:
        prov["kind"] = kind
    nested = raw.get("provenance")
    if isinstance(nested, dict):
        for k, v in nested.items():
            if k not in prov and v is not None:
                prov[k] = v
    for extra in ("plugin", "plugin_id", "author"):
        if raw.get(extra) is not None:
            prov[extra] = raw[extra]
    return prov


def _business_logic_atom(raw: Any, index: int) -> Optional[RuleAtom]:
    path = f"guidance.injections.business_logic[{index}]"
    if isinstance(raw, str):
        return RuleAtom(
            id=f"r{index + 1}",
            path=path,
            kind="business_logic",
            text=raw,
            structured={"rule": raw},
            provenance={"id": f"r{index + 1}", "path": path, "source": "operator"},
        )
    if isinstance(raw, dict):
        rid = str(raw.get("id") or f"r{index + 1}")
        text = str(raw.get("rule") or raw.get("text") or "")
        if not text:
            # Structured-only rules: synthesize readable text from effect/tool
            effect = raw.get("effect")
            tool = raw.get("tool")
            if effect and tool:
                text = f"{effect}:{tool}"
            else:
                text = str({k: raw[k] for k in raw if k not in ("id",)})
        effect = raw.get("effect")
        if isinstance(effect, str):
            effect = effect.strip().lower() or None
            if effect and effect not in STRUCTURED_EFFECTS:
                # Unknown effect still recorded but not hard-matrix'd
                pass
        else:
            effect = None
        tool = raw.get("tool")
        if tool is not None:
            tool = str(tool).strip().lower() or None
        when = _parse_when(raw)
        priority = raw.get("priority")
        try:
            priority_i = int(priority) if priority is not None else None
        except (TypeError, ValueError):
            priority_i = None
        return RuleAtom(
            id=rid,
            path=path,
            kind="business_logic",
            text=text,
            structured=dict(raw),
            effect=effect if effect in STRUCTURED_EFFECTS else effect,
            tool=tool,
            when=when or None,
            priority=priority_i,
            provenance=_parse_provenance(raw, path, rid),
        )
    return None


def _schema_text(schema: Any) -> str:
    if isinstance(schema, dict):
        try:
            return json.dumps(schema, sort_keys=True)[:500]
        except Exception:
            return str(schema)[:500]
    return str(schema)[:500]


def structured_open_rules(atoms: list[RuleAtom]) -> list[RuleAtom]:
    """Atoms that carry a known structured effect + tool (hard-lintable)."""
    out = []
    for a in atoms:
        if a.effect in STRUCTURED_EFFECTS and a.tool:
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_findings(findings: Iterable[Finding]) -> tuple[int, str]:
    """Return (conflict_score 0–100, severity band).

    Score remains the V1 heuristic sum (secondary signal). Prefer
    ``hard_finding_count`` / ``open_vs_locked_count`` for gates; soft NL is
    advisory regardless of band.
    """
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
# Soft checkers (V1 heuristics — advisory / low–medium confidence)
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
    """always/must vs never/must-not over shared topic + tool (soft NL)."""
    findings: list[Finding] = []
    bl = [a for a in atoms if a.kind == "business_logic" and a.text]
    for a, b in combinations(bl, 2):
        a_pos, a_neg = bool(_ALWAYS.search(a.text)), bool(_NEVER.search(a.text))
        b_pos, b_neg = bool(_ALWAYS.search(b.text)), bool(_NEVER.search(b.text))
        if not ((a_pos and b_neg) or (a_neg and b_pos)):
            continue
        shared = _shared_tokens(a.text, b.text)
        tools_a, tools_b = _tools_in_text(a.text), _tools_in_text(b.text)
        tool_overlap = tools_a & tools_b
        if not shared and not tool_overlap:
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
            layer="soft",
            confidence="low",
            rule_id_a=a.id,
            rule_id_b=b.id,
        ))
    return findings


def check_exclusive_preferred_tools(atoms: list[RuleAtom]) -> list[Finding]:
    """Two open rules that prefer different tools for the same topic (soft)."""
    findings: list[Finding] = []
    candidates: list[tuple[RuleAtom, set[str], set[str]]] = []
    for a in atoms:
        if a.kind not in ("business_logic", "optimal_path") or not a.text:
            continue
        if not (_PREFER.search(a.text) or _ALWAYS.search(a.text) or a.kind == "optimal_path"):
            continue
        tools = _tools_in_text(a.text)
        if a.kind == "optimal_path" and a.structured:
            pipe = a.structured.get("pipeline") or []
            if isinstance(pipe, list) and pipe and isinstance(pipe[0], dict):
                v = pipe[0].get("verb")
                if v:
                    tools = {str(v).lower()} | tools
        if not tools:
            continue
        content = set(re.findall(r"[a-z0-9_]{4,}", a.text.lower()))
        candidates.append((a, tools, content))

    for (a, ta, ca), (b, tb, cb) in combinations(candidates, 2):
        if ta == tb:
            continue
        overlap = ca & cb
        ea = (a.structured or {}).get("entity_type")
        eb = (b.structured or {}).get("entity_type")
        same_et = ea and eb and ea == eb
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
                    layer="soft",
                    confidence="medium",
                    rule_id_a=a.id,
                    rule_id_b=b.id,
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
                layer="soft",
                confidence="low",
                rule_id_a=a.id,
                rule_id_b=b.id,
            ))
    return findings


def _optimal_path_intent_overlap(a: dict, b: dict) -> bool:
    pa = a.get("intent_pattern") or {}
    pb = b.get("intent_pattern") or {}
    if not isinstance(pa, dict) or not isinstance(pb, dict):
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
    """deny_when vs require on same entity that cannot both hold (hard)."""
    findings: list[Finding] = []
    bl = [a for a in atoms if a.kind == "business_logic" and a.structured]
    for a, b in combinations(bl, 2):
        sa, sb = a.structured or {}, b.structured or {}
        ea, eb = sa.get("entity_type"), sb.get("entity_type")
        if ea and eb and ea != eb:
            continue
        deny_a, req_a = sa.get("deny_when"), sa.get("require")
        deny_b, req_b = sb.get("deny_when"), sb.get("require")
        for pred_deny, pred_req, path_d, path_r, text_d, text_r, id_d, id_r in (
            (deny_a, req_b, a.path, b.path, a.text, b.text, a.id, b.id),
            (deny_b, req_a, b.path, a.path, b.text, a.text, b.id, a.id),
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
                    layer="hard",
                    confidence="high",
                    rule_id_a=id_d,
                    rule_id_b=id_r,
                ))
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
                    layer="hard",
                    confidence="high",
                    rule_id_a=a.id,
                    rule_id_b=b.id,
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
    if not isinstance(req_cond, dict) and not isinstance(deny_cond, dict):
        return req_cond == deny_cond
    if not isinstance(req_cond, dict) and isinstance(deny_cond, dict):
        return _value_matches_ops(req_cond, deny_cond)
    if isinstance(req_cond, dict) and not isinstance(deny_cond, dict):
        if set(req_cond.keys()) <= {"=="} and req_cond.get("==") == deny_cond:
            return True
        return False
    assert isinstance(req_cond, dict) and isinstance(deny_cond, dict)
    if "==" in req_cond and "==" in deny_cond and req_cond["=="] == deny_cond["=="]:
        return True
    if "==" in req_cond:
        return _value_matches_ops(req_cond["=="], deny_cond)
    try:
        if ">=" in req_cond and ">" in deny_cond:
            if float(req_cond[">="]) > float(deny_cond[">"]):
                return True
            if float(req_cond[">="]) == float(deny_cond[">"]):
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
                layer="soft",
                confidence="medium",
                rule_id_a=a.id,
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
                    layer="soft",
                    confidence="medium",
                    rule_id_a=a.id,
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
                    layer="soft",
                    confidence="medium",
                    rule_id_a=a.id,
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
                        layer="soft",
                        confidence="medium",
                        rule_id_a=a.id,
                    ))
                elif as_set:
                    findings.append(Finding(
                        check_id="optimal_path_unknown_return",
                        severity="medium",
                        message=f"return[] name {rs!r} is not a step 'as' binding {sorted(as_set)}",
                        path_a=f"{a.path}.return",
                        rule_a=a.text,
                        layer="soft",
                        confidence="medium",
                        rule_id_a=a.id,
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
                layer="soft",
                confidence="high",
                rule_id_a=prev.id,
                rule_id_b=a.id,
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
                layer="soft",
                confidence="medium",
                rule_id_a=prev.id,
                rule_id_b=a.id,
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
        et = a.structured.get("entity_type") or (a.when or {}).get("entity_type")
        if not et:
            continue
        if et not in ets:
            findings.append(Finding(
                check_id="schema_unknown_entity",
                severity="medium",
                message=f"business rule entity_type {et!r} not in MINI-SCHEMA {sorted(ets)}",
                path_a=a.path,
                rule_a=a.text,
                layer="soft",
                confidence="medium",
                rule_id_a=a.id,
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
                layer="soft",
                confidence="medium",
                rule_id_a=a.id,
            ))
    return findings


# ---------------------------------------------------------------------------
# V2 hard structured effect conflicts
# ---------------------------------------------------------------------------

def _when_compatible(w1: Optional[dict], w2: Optional[dict]) -> bool:
    """True when two when-clauses can both apply (overlap).

    Empty/missing when is treated as universal (matches any).
    entity_type must agree when both specify it.
    Other keys: if both specify the same key with different values → no overlap.
    """
    a = w1 or {}
    b = w2 or {}
    if not a or not b:
        return True
    keys = set(a) | set(b)
    for k in keys:
        if k not in a or k not in b:
            continue
        va, vb = a[k], b[k]
        if va != vb:
            return False
    return True


def _when_label(when: Optional[dict]) -> str:
    if not when:
        return "*"
    et = when.get("entity_type")
    if et and len(when) == 1:
        return f"entity_type={et}"
    try:
        return json.dumps(when, sort_keys=True, default=str)
    except Exception:
        return str(when)


def check_hard_effect_conflicts(atoms: list[RuleAtom]) -> list[Finding]:
    """Deterministic hard conflicts between structured open-rule effects.

    Hard conflict = opposing effects in the same (tool × when) space, e.g.
    ``prefer_tool:find`` vs ``forbid_tool:find`` for the same entity_type.
    """
    findings: list[Finding] = []
    structured = structured_open_rules(atoms)
    for a, b in combinations(structured, 2):
        if a.tool != b.tool:
            # Different tools: prefer_tool X vs prefer_tool Y under same when
            # is a soft exclusive preference when both are prefer/require
            if (
                a.effect in ("prefer_tool", "require_tool")
                and b.effect in ("prefer_tool", "require_tool")
                and _when_compatible(a.when, b.when)
            ):
                findings.append(Finding(
                    check_id="hard_exclusive_prefer_tools",
                    severity="medium",
                    message=(
                        f"Structured rules prefer different tools under "
                        f"{_when_label(a.when or b.when)}: "
                        f"{a.effect}:{a.tool} vs {b.effect}:{b.tool}"
                    ),
                    path_a=a.path,
                    path_b=b.path,
                    rule_a=a.text,
                    rule_b=b.text,
                    layer="hard",
                    confidence="high",
                    rule_id_a=a.id,
                    rule_id_b=b.id,
                ))
            continue
        if (a.effect, b.effect) not in _OPPOSING_EFFECTS:
            continue
        if not _when_compatible(a.when, b.when):
            continue
        findings.append(Finding(
            check_id="hard_effect_conflict",
            severity="high",
            message=(
                f"Opposing structured effects on tool {a.tool!r} "
                f"({a.effect} vs {b.effect}) when {_when_label(a.when or b.when)}"
            ),
            path_a=a.path,
            path_b=b.path,
            rule_a=a.text,
            rule_b=b.text,
            layer="hard",
            confidence="high",
            rule_id_a=a.id,
            rule_id_b=b.id,
        ))
    return findings


# ---------------------------------------------------------------------------
# V2 open vs locked
# ---------------------------------------------------------------------------

def _locked_text_surfaces(chat_req: dict) -> str:
    """Concatenate locked prose used for best-effort stance extraction."""
    parts: list[str] = []
    instr = chat_req.get("instructions") or {}
    if isinstance(instr, dict):
        for key in ("system_prompt", "verb_usage_guide", "response_expectations"):
            v = instr.get(key)
            if isinstance(v, str) and v.strip():
                # Strip runtime brief if present
                for marker in ("\n\n## SCOPE BRIEF", "\n\n## MINI-SCHEMA"):
                    i = v.find(marker)
                    if i >= 0:
                        v = v[:i]
                parts.append(v)
    # messages[0].content locked prefix
    msgs = chat_req.get("messages") or []
    if msgs and isinstance(msgs[0], dict):
        content = msgs[0].get("content") or ""
        if isinstance(content, str):
            for marker in ("\n\n## SCOPE BRIEF", "\n\n## MINI-SCHEMA"):
                i = content.find(marker)
                if i >= 0:
                    content = content[:i]
            parts.append(content)
    return "\n".join(parts)


def extract_locked_tool_stances(chat_req: dict) -> dict[str, set[str]]:
    """Best-effort tool prefer/forbid sets from locked surfaces.

    Incomplete by design — free-text locked carts cannot be fully formalized.
    Returns ``{"prefer": {...}, "forbid": {...}}``.
    """
    prefer: set[str] = set()
    forbid: set[str] = set()
    text = _locked_text_surfaces(chat_req)
    catalog = _catalog_verb_names(chat_req)
    for m in _LOCKED_PREFER_TOOL.finditer(text):
        tool = m.group(1).lower()
        if not catalog or tool in catalog or tool in _TOOL_TOKEN.pattern:
            prefer.add(tool)
    for m in _LOCKED_FORBID_TOOL.finditer(text):
        tool = m.group(1).lower()
        # Filter common false positives
        if tool in ("the", "a", "an", "to", "for", "any", "all", "this", "that"):
            continue
        if not catalog or tool in catalog:
            forbid.add(tool)
    # Keep only known tools when catalog is available
    if catalog:
        prefer &= catalog
        forbid &= catalog
    return {"prefer": prefer, "forbid": forbid}


def check_open_vs_locked(
    atoms: list[RuleAtom],
    chat_req: dict,
) -> list[Finding]:
    """Flag open structured rules that oppose locked tool constraints.

    Primary class (MVP): open ``forbid_tool`` vs locked prefer/allow of same tool;
    open ``prefer_tool``/``require_tool`` vs locked forbid of same tool.
    """
    findings: list[Finding] = []
    stances = extract_locked_tool_stances(chat_req)
    locked_prefer = stances["prefer"]
    locked_forbid = stances["forbid"]
    if not locked_prefer and not locked_forbid:
        return findings

    for a in structured_open_rules(atoms):
        tool = a.tool or ""
        if a.effect == "forbid_tool" and tool in locked_prefer:
            findings.append(Finding(
                check_id="open_vs_locked_forbid_vs_prefer",
                severity="high",
                message=(
                    f"Open rule forbids tool {tool!r} but locked cart prefers/allows it"
                ),
                path_a=a.path,
                path_b="instructions/system_prompt|verb_usage_guide",
                rule_a=a.text,
                rule_b=f"locked prefer:{tool}",
                layer="open_vs_locked",
                confidence="medium",
                rule_id_a=a.id,
            ))
        if a.effect in ("prefer_tool", "require_tool", "allow_tool") and tool in locked_forbid:
            findings.append(Finding(
                check_id="open_vs_locked_prefer_vs_forbid",
                severity="high",
                message=(
                    f"Open rule prefers/requires tool {tool!r} but locked cart forbids it"
                ),
                path_a=a.path,
                path_b="instructions/system_prompt|verb_usage_guide",
                rule_a=a.text,
                rule_b=f"locked forbid:{tool}",
                layer="open_vs_locked",
                confidence="medium",
                rule_id_a=a.id,
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
    hard_conflicts: bool = True,
    soft_nl: bool = True,
    open_vs_locked: bool = True,
    config: Optional[CatalogLintConfig] = None,
) -> ConflictReport:
    """Analyze a chat_request for conflicting open rules (and open-vs-locked).

    Pure / read-only: does not mutate ``chat_req``. Contract-locked paths are
    never rewritten.

    Args:
        chat_req: Loaded chat_request document (dict).
        include_structural: Run optimal_paths pipeline shape checks (soft).
        include_schema: Check business_logic entity/fields against MINI-SCHEMA.
        hard_conflicts: Run structured effect + predicate hard checks (V2).
        soft_nl: Run V1-style NL heuristics (soft / low confidence).
        open_vs_locked: Run open structured vs locked stance checks (V2).
        config: Optional ``CatalogLintConfig`` (overrides boolean flags when set).
    """
    if config is not None:
        include_structural = config.include_structural
        include_schema = config.include_schema
        hard_conflicts = config.hard_conflicts
        soft_nl = config.soft_nl
        open_vs_locked = config.open_vs_locked
        mode = config.mode
    else:
        mode = "assemble"

    if not isinstance(chat_req, dict):
        return ConflictReport(
            conflict_score=0,
            severity="none",
            finding_count=0,
            findings=[],
            open_rule_count=0,
            mode=mode,
        )

    atoms = inventory_open_rules(chat_req)
    findings: list[Finding] = []

    # --- Hard layer (structured) ---
    if hard_conflicts:
        findings.extend(check_hard_effect_conflicts(atoms))
        findings.extend(check_structured_predicate_clash(atoms))

    # --- Soft layer (V1 NL + hygiene) ---
    if soft_nl:
        findings.extend(check_negation_pairs(atoms))
        findings.extend(check_exclusive_preferred_tools(atoms))
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

    # --- Open vs locked ---
    if open_vs_locked:
        findings.extend(check_open_vs_locked(atoms, chat_req))

    # Stable order: layer (hard first), severity, check_id, path
    layer_rank = {"hard": 0, "open_vs_locked": 1, "soft": 2}
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(
        key=lambda f: (
            layer_rank.get(f.layer, 9),
            sev_rank.get(f.severity, 9),
            f.check_id,
            f.path_a,
            f.path_b or "",
        )
    )

    score, band = score_findings(findings)
    hard_n = sum(1 for f in findings if f.layer == "hard")
    soft_n = sum(1 for f in findings if f.layer == "soft")
    ovl_n = sum(1 for f in findings if f.layer == "open_vs_locked")
    struct_n = len(structured_open_rules(atoms))

    return ConflictReport(
        conflict_score=score,
        severity=band,
        finding_count=len(findings),
        findings=findings,
        open_rule_count=len(atoms),
        locked_paths_note=LOCKED_PATHS_NOTE,
        hash_excluded_roots=list(HASH_EXCLUDED_ROOTS),
        locked_pointers=list(LOCKED_POINTERS),
        lint_version=LINT_VERSION,
        hard_finding_count=hard_n,
        soft_finding_count=soft_n,
        open_vs_locked_count=ovl_n,
        structured_rule_count=struct_n,
        mode=mode,
    )


def hash_policy_summary() -> dict[str, Any]:
    """Document locked vs open paths for debug UIs and CLI headers."""
    return {
        "lint_version": LINT_VERSION,
        "hash_excluded_roots": list(HASH_EXCLUDED_ROOTS),
        "locked_pointers": list(LOCKED_POINTERS),
        "structured_effects": sorted(STRUCTURED_EFFECTS),
        "layers": ["hard", "open_vs_locked", "soft"],
        "note": [
            LOCKED_PATHS_NOTE,
            "Open insert surface for operators/plugins: guidance.* "
            "(especially injections.business_logic and optimal_paths).",
            "Hard conflicts use structured effect/tool/when atoms (ZC-36). "
            "Soft NL (ZC-35) is advisory / low confidence only.",
            "Open-vs-locked extraction from locked prose is best-effort.",
        ],
    }


def structured_rule_schema() -> dict[str, Any]:
    """Document the structured open-rule atom schema (authoring / migration)."""
    return {
        "version": LINT_VERSION,
        "description": (
            "Structured open business rules for deterministic hard conflict detection. "
            "Prose may remain in `rule` as rationale / LLM-facing text; hard lint keys "
            "off effect + tool + when."
        ),
        "fields": {
            "id": "stable rule id (required for actionable reports)",
            "effect": sorted(STRUCTURED_EFFECTS),
            "tool": "verb/tool name, e.g. find",
            "when": {
                "entity_type": "optional entity scope",
                "...": "additional equality keys for finer when-matching",
            },
            "priority": "optional int (higher may win later; not auto-resolved yet)",
            "source": sorted(PROVENANCE_SOURCES),
            "kind": sorted(PROVENANCE_KINDS),
            "rule": "optional free-text rationale (soft NL only)",
            "entity_type": "legacy top-level alias folded into when.entity_type",
            "deny_when / require": "structured predicates (hard via structured_predicate_clash)",
        },
        "examples": [
            {
                "id": "prefer-find-beer",
                "effect": "prefer_tool",
                "tool": "find",
                "when": {"entity_type": "Beer"},
                "priority": 10,
                "source": "operator",
                "kind": "routing",
                "rule": "Prefer find for Beer lookups.",
            },
            {
                "id": "ban-find-beer",
                "effect": "forbid_tool",
                "tool": "find",
                "when": {"entity_type": "Beer"},
                "priority": 50,
                "source": "plugin",
                "kind": "routing",
                "rule": "Do not use find for Beer.",
            },
        ],
        "migration": (
            "Keep free-text rules during the compat period; add effect/tool/when "
            "alongside `rule` to enable hard lint. Soft NL continues for prose-only."
        ),
    }
