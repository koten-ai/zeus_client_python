# Guide: Chat Request Conflict Lint (ZC-35 V1 + ZC-36 V2)

**Date**: 2026-07-17  
**Feature**: Detect conflicting business rules in `chat_request*.json`  
**Status**: Active (V2 MVP)  
**Jira**: [ZC-36](https://kotenai.atlassian.net/browse/ZC-36) (V2), [ZC-35](https://kotenai.atlassian.net/browse/ZC-35) (V1 soft)  
**Related**: README “Lint catalog rules”, `src/zeus/lint.py`, `src/contract_hash.py`, `scripts/lint_chat_request.py`

---

## 0. V1 vs V2 (read this first)

| | V1 (ZC-35) | V2 (ZC-36) |
|--|------------|------------|
| Detector | Client heuristics (regex always/never, tool tokens, dups) | **Hard**: structured effects; **Soft**: keep heuristics; Deep LLM offline only (not default) |
| When | CLI on demand; agent every turn if `guidance.debug` | **Once per catalog assembly** (cache); not every tool round-trip |
| Who | Client code only | Client hard/soft; Zeus still owns contract hash |
| Blocks chat? | Never | Never on soft; CI may `--fail-on hard` |
| Contract-locked | Not rewritten | Still not rewritten; **open vs locked flagged** |
| Score | 0–100 from heuristics | **Hard findings primary**; score secondary / calibrated |

**Product goal:** Structure + assemble-time + provenance + open-vs-locked; NL is a side smoke detector — not the foundation.

V1 remains the **soft / low-confidence** layer. Do not treat a 0–100 score as a chat gate.

### V2 layers

1. **Layer 0 — Provenance** — every open insert should carry `id`, `path`, optional `source` / `kind` / `plugin`.
2. **Layer 1 — Structured open rules (hard)** — `effect` + `tool` + `when` atoms; deterministic conflict matrix.
3. **Layer 2 — Soft NL (V1)** — always/never, duplicates, optimal_paths hygiene; `confidence: low|medium`.
4. **Layer 3 — Open vs locked** — open structured rules that oppose locked prefer/forbid stances (best-effort extraction from locked prose).

### Structured open-rule schema (migration)

Prefer authoring structured atoms; keep free-text `rule` as rationale during the compat period:

```json
{
  "id": "prefer-find-beer",
  "effect": "prefer_tool",
  "tool": "find",
  "when": { "entity_type": "Beer" },
  "priority": 10,
  "source": "operator",
  "kind": "routing",
  "rule": "Prefer find for Beer lookups."
}
```

Known `effect` values: `prefer_tool`, `forbid_tool`, `require_tool`, `allow_tool`.

CLI schema dump: `python scripts/lint_chat_request.py --schema`  
Library: `from zeus_client import structured_rule_schema`.

### Config / kill switches

```text
guidance.catalog_lint:
  mode: off | assemble | debug | ci
  hard_conflicts: true
  soft_nl: true
  open_vs_locked: true
  deep_llm: false          # reserved; never default-on
  fail_on: none | hard | high | medium | low
```

Env: `ZEUS_CATALOG_LINT_MODE`, `ZEUS_CATALOG_LINT_FAIL_ON`.

| Goal | How |
|------|-----|
| No check during chat | `mode: off` (default unless `guidance.debug`) |
| Authoring / session start | `mode: assemble` or `debug` |
| CI gate | `mode: ci`, `--fail-on hard` |
| Never block user turn on soft NL | Product invariant (agent never fails the turn) |

### Assemble-time cache

Cache key = `hash(locked contract material) + hash(open rule atoms) + config flags`.  
Entry points: `lint_catalog_assembled(chat_req)` (agent uses this). Invalidate by changing open rules or stamp hash. Soft NL is not re-run every tool round.

---

## 1. Overview

### Purpose

Zeus Client loads stamped V2 `chat_request` catalogs and lets operators/plugins inject **unbounded** business rules into hash-excluded surfaces (`guidance.*`). Over time those open rules can contradict each other, for example:

- Structured: `prefer_tool:find` vs `forbid_tool:find` for the same `entity_type`
- Open `forbid_tool:find` while locked cart says “prefer find”
- Soft: “Always prefer `find` for Beer” vs “Never use `find` for Beer”
- `deny_when: abv > 7` vs `require: abv >= 8` on the same entity
- Two `optimal_paths` that match the same intent but prefer different entry verbs
- Pipeline templates that would 400 on Zeus (`missing as`, `return[]` lists verbs, unknown verb)

Contract verify / hash drift only protect **locked** rules content; they do not score open-rule conflicts or open-vs-locked fights.

The linter is **read-only** and:

1. Inventories open rule atoms with JSON paths + provenance  
2. Runs hard structured + soft NL + open-vs-locked checkers  
3. Produces a `ConflictReport` with hard/soft/open_vs_locked counts, optional score, findings  
4. **Never rewrites** contract-locked content  
5. Surfaces via **Python API**, **CLI**, and optional **agent trace** (assemble/debug/ci)  

### Scope

| In scope (MVP) | Out of scope |
|----------------|--------------|
| Offline lint of any `chat_request` dict / file | Auto-merge / auto-edit of rules |
| Hard structured effects + soft NL + open-vs-locked | Full formal logic / theorem prover over free text |
| Assemble-time cache | Per-turn LLM conflict auditor |
| CLI + library + agent attach | Replacing Zeus contract `/verify` |
| CI `--fail-on hard` | Client rewrite of hashed content |
| Document locked vs open paths | Workbench UI button (Phase D) |

### Entry points

| Surface | Entry |
|---------|--------|
| Library | `from zeus_client import lint_chat_request, lint_catalog_assembled` |
| Report types | `ConflictReport`, `Finding`, `CatalogLintConfig`, `hash_policy_summary` |
| Schema | `structured_rule_schema()` / CLI `--schema` |
| CLI | `python scripts/lint_chat_request.py <path>` |
| Policy dump | `python scripts/lint_chat_request.py --policy` |
| Agent (opt-in) | `guidance.debug` or `guidance.catalog_lint.mode` ∈ assemble/debug/ci |
| Implementation | `src/zeus/lint.py` |
| Policy constants | `src/contract_hash.py` (`HASH_EXCLUDED_ROOTS`, `LOCKED_POINTERS`) |
---

## 2. Problem context (why this exists)

### Contract model (recap)

A standardized V2 catalog is a JSON envelope roughly:

```text
_format: zeus.chat_request.v2
contract: { id, hash, ... }          # stamp metadata (excluded from hash)
guidance: { ... }                    # advisory (excluded from hash)
instructions: { system_prompt, … }   # LOCKED (hashed)
masq: { costs, tier_order }          # LOCKED
verbs: [ … ]                         # LOCKED
messages: [ { role: system, content } ]  # LOCKED (brief suffix stripped)
metadata: { … }                      # excluded
_* : operator keys                   # excluded
```

Hashing (server authority; client fallback in `compute_contract_hash`):

1. Strip excluded roots (`guidance`, `contract`, `metadata`, `_*`)  
2. Strip runtime knobs (`targets`, `model`, `temperature`, …)  
3. Truncate any string at `## SCOPE BRIEF` / `## MINI-SCHEMA`  
4. Canonicalize + MD5 → `md5:…`

So operators can freely edit **`guidance`** without invalidating the stamp. That is intentional — and it is also how unbounded, conflicting rules accumulate.

### Open insert surfaces the client already supports

| Mechanism | Path / API | Hash impact |
|-----------|------------|-------------|
| Business rules | `guidance.injections.business_logic` via `inject_business_logic` | None (guidance excluded) |
| Render into prompt | `apply_injected_business_logic` after SCOPE BRIEF marker | None (post-brief stripped) |
| Structured row schema | `guidance.injections.output_schema` | None |
| Optimal paths | `guidance.optimal_paths[]` | None |
| Debug / compliance self-report | `guidance.debug`, `report_compliance` | None |
| Runtime row audit | `audit_rows_against_rules` | N/A (post-tool, not static lint) |
| Agent hooks | `AgentHooks` crawl/walk/run | Not in the JSON document |

ZC-35 is the **static pre-flight / authoring** counterpart to runtime `audit_rows_against_rules`.

---

## 3. Architecture & flow

```text
chat_request JSON (file or in-memory dict)
              │
              ▼
   inventory_open_rules()
     • business_logic[] → RuleAtom(kind=business_logic)
     • optimal_paths[]  → RuleAtom(kind=optimal_path)
     • output_schema    → RuleAtom(kind=output_schema)
              │
              ▼
   checkers (composable)
     • negation_pair
     • exclusive_preferred_tools
     • structured_predicate_clash
     • duplicate_rule_id / duplicate_rule_text
     • optimal_path_* (structural)
     • schema_unknown_entity / schema_unknown_fields
              │
              ▼
   score_findings()
     weights: high=25, medium=10, low=3
     score = min(100, sum)
     band: 0 none · 1–24 low · 25–49 medium · 50+ high
              │
              ├── Python API  → ConflictReport
              ├── CLI         → text or JSON
              └── setup_turn_context (if guidance.debug)
                              → trace["catalog_lint"] + notes line
```

### Design principles

1. **Heuristic-first** — no LLM call, no network, no Zeus dependency for lint itself.  
2. **Read-only** — never mutates the input dict; never rewrites locked paths.  
3. **Pure function** — `lint_chat_request(chat_req) -> ConflictReport`.  
4. **Explainable score** — linear weighted sum of severities, capped at 100.  
5. **Same policy as hash** — locked/open lists live next to `_strip_for_hash` so docs and code do not drift.

---

## 4. Locked vs open paths (authoritative client view)

These constants are exported from `contract_hash` and re-exposed via `hash_policy_summary()`.

### Hash-excluded (open / advisory) — primary lint target

| Root / marker | Role |
|---------------|------|
| `guidance` | Entire tree: `injections`, `optimal_paths`, `debug`, `assembler_hints`, `query_decomposition`, `strategy_boosts`, … |
| `contract` | Stamp metadata (`id`, `hash`, `computed_at`, …) |
| `metadata` | Advisory tags/notes |
| `_*` | Underscore-prefixed tooling keys (`_format`, `_hash`, `_comment`, …) |
| Content after `## SCOPE BRIEF` / `## MINI-SCHEMA` | Runtime brief + injected business-rules section |

### Contract-locked (hashed) — do **not** “fix” by rewriting

| Pointer | Role |
|---------|------|
| `/instructions/system_prompt` | Core system rules text |
| `/instructions/verb_usage_guide` | Verb authoring guide |
| `/instructions/verb_order` | Preferred verb order |
| `/instructions/response_expectations` | Response shape expectations |
| `/masq` | Cost tiers / masq model |
| `/verbs` | Tool/verb schemas (promoted to LLM tools at call time only) |
| `/messages/*/content` | System message content (brief suffix stripped for hash) |

Also stripped as non-rules knobs (not “open business rules”, just non-hashed): `targets`, `model`, `tool_choice`, `temperature`, `top_p`, `max_tokens`.

**Important:** Adding a top-level `tools` alias of `verbs` **changes the hash**. Load path must not copy verbs→tools; see `tools_from_chat_request`.

### What the linter will / will not do to locked content

| Action | Behavior |
|--------|----------|
| Report findings on open paths | Yes |
| Suggest which open rules conflict | Yes (paths + text snippets) |
| Mutate `instructions` / `verbs` / pre-brief `messages` | **No** |
| Re-stamp or re-hash as a “fix” | **No** |
| Cross-check open rule vs locked system prompt NL | Not in MVP (phase 2 informational only) |

Every report includes:

```text
Locked (hashed) content is never rewritten by this linter.
Findings target open/hash-excluded surfaces only (guidance, contract, metadata, _*).
```

---

## 5. Data model

### `RuleAtom`

One open fragment with a stable path:

| Field | Type | Meaning |
|-------|------|---------|
| `id` | `str` | Rule id or synthetic (`r1`, `op1`, …) |
| `path` | `str` | JSON path, e.g. `guidance.injections.business_logic[0]` |
| `kind` | `str` | `business_logic` \| `optimal_path` \| `output_schema` |
| `text` | `str` | Free text used by NL heuristics |
| `structured` | `dict \| None` | Original object (`deny_when`, `pipeline`, …) |
| `locked` | `bool` | Always `False` for open inventory in MVP |

### `Finding`

| Field | Type | Meaning |
|-------|------|---------|
| `check_id` | `str` | Checker name (see §6) |
| `severity` | `str` | `high` \| `medium` \| `low` |
| `message` | `str` | Human-readable explanation |
| `path_a` | `str` | Primary path |
| `path_b` | `str \| None` | Second path for pairwise conflicts |
| `rule_a` / `rule_b` | `str \| None` | Text snippets (truncated in CLI render) |

### `ConflictReport`

| Field | Type | Meaning |
|-------|------|---------|
| `conflict_score` | `int` | 0–100 |
| `severity` | `str` | `none` \| `low` \| `medium` \| `high` |
| `finding_count` | `int` | `len(findings)` |
| `findings` | `list[Finding]` | Sorted by severity, then `check_id`, then path |
| `open_rule_count` | `int` | Number of inventoried atoms |
| `locked_paths_note` | `str` | Safety disclaimer |
| `hash_excluded_roots` | `list[str]` | Policy snapshot |
| `locked_pointers` | `list[str]` | Policy snapshot |

Helpers:

- `report.to_dict()` — JSON-serializable (for CLI `--json` and `trace["catalog_lint"]`)  
- `report.summary_line()` — one-liner for `trace["notes"]`  
- `report.format_text()` — multi-line human report  

### Scoring formula

```text
SEVERITY_WEIGHTS = { high: 25, medium: 10, low: 3 }

conflict_score = min(100, Σ weight[severity] for each finding)

severity band:
  score == 0          → none
  1  <= score <= 24   → low
  25 <= score <= 49   → medium
  score >= 50         → high
```

Examples:

| Findings | Score | Band |
|----------|-------|------|
| (none) | 0 | none |
| 1× low | 3 | low |
| 3× medium | 30 | medium |
| 2× high | 50 | high |
| 2× high + 3× medium + 1× low | 100 (capped) | high |

---

## 6. Checkers (heuristic catalog)

Each checker returns zero or more `Finding`s. All run by default except as noted on `lint_chat_request(..., include_structural=, include_schema=)`.

### 6.1 `negation_pair` — severity **high**

**Target:** pairs of `business_logic` free-text rules.

**Signal:** one rule matches positive modality (`always`, `must`, `prefer`, `only`, …) and the other matches negative modality (`never`, `must not`, `avoid`, `don't`, …), **and** they share:

- content tokens (length ≥ 4, stopwords removed), and/or  
- tool tokens (`find`, `search`, `get`, …), and/or  
- the same structured `entity_type`

**Example that fires:**

```json
{"id": "a", "rule": "Always prefer find for Beer lookups."}
{"id": "b", "rule": "Never use find for Beer queries."}
```

### 6.2 `exclusive_preferred_tools` — **high** (business_logic) / **medium** (optimal_paths)

**Target:** rules that express a preferred tool / entry verb.

- **business_logic:** prefer/always language + different tool sets + topical overlap → **high**  
- **optimal_paths:** overlapping `intent_pattern` (same `output`, overlapping `target_entity_types` or `*`) but different first pipeline verbs → **medium**

### 6.3 `structured_predicate_clash` — **high** / **medium**

**Target:** structured `deny_when` / `require` on business rules.

- Cross pair: `deny_when` of A vs `require` of B (same entity when both set) where satisfying `require` always matches `deny` → **high**  
  - Equality: require `state == CA` and deny `state == CA`  
  - Intervals: require `abv >= 8` and deny `abv > 7`  
- Paired `deny_when` with opposite exact equalities on the sole shared field → **medium**

Free-text-only rules without predicates are not checked here (they may still hit NL checkers).

### 6.4 `duplicate_rule_id` / `duplicate_rule_text` — **low**

- Same `id` on two business_logic entries  
- Same normalized whitespace-collapsed lowercase text  

### 6.5 Optimal path structure — **medium** (`include_structural=True`)

| `check_id` | Condition |
|------------|-----------|
| `optimal_path_too_many_steps` | `len(pipeline) > 8` |
| `optimal_path_missing_as` | step lacks unique `as` binding |
| `optimal_path_unknown_verb` | step `verb` not in catalog `verbs`/`tools` names |
| `optimal_path_return_is_verb` | `return[]` entry equals a verb name instead of an `as` |
| `optimal_path_unknown_return` | `return[]` entry not in step `as` set |

Catalog verb names come from `tools_from_chat_request` (does not mutate the document).

### 6.6 Schema orphans — **medium** (`include_schema=True`)

When MINI-SCHEMA is present (SCOPE BRIEF merged / fixture brief):

| `check_id` | Condition |
|------------|-----------|
| `schema_unknown_entity` | `entity_type` not in mini-schema |
| `schema_unknown_fields` | listed `fields` not on that entity |

If no mini-schema is available, schema checks are skipped (same spirit as inject-time validation when brief is missing).

---

## 7. Inventory sources (what is scanned)

| Source path | Kind | Notes |
|-------------|------|-------|
| `guidance.injections.business_logic[]` | `business_logic` | String → `{rule}`; dict keeps `id`, `entity_type`, `fields`, `deny_when`, `require`, … |
| `guidance.optimal_paths[]` | `optimal_path` | Text built from `when_to_use`, `description`, `intent`, `notes`, pipeline verbs |
| `guidance.injections.output_schema` | `output_schema` | Inventoried for completeness; limited dedicated checkers in v1 |

Not scanned in MVP:

- Locked `instructions.system_prompt` body (except as non-target)  
- `AgentHooks` runtime injections  
- Live Zeus server state  

---

## 8. How to use

### 8.1 Python API

```python
import json
from pathlib import Path
from zeus_client import lint_chat_request, hash_policy_summary

chat_req = json.loads(Path("chat_request_analytics_v2.json").read_text())

report = lint_chat_request(chat_req)
# Optional flags:
#   include_structural=True  — pipeline shape checks
#   include_schema=True      — MINI-SCHEMA entity/field checks

print(report.summary_line())
# catalog_lint: score=0 severity=none findings=0 open_rules=…

print(report.conflict_score, report.severity, report.finding_count)
for f in report.findings:
    print(f"[{f.severity}] {f.check_id}: {f.message}")
    print(f"  {f.path_a}" + (f" vs {f.path_b}" if f.path_b else ""))

# JSON for UIs / CI artifacts
payload = report.to_dict()

# Locked vs open documentation
print(hash_policy_summary())
```

**Hash safety check (recommended when validating tooling):**

```python
from zeus_client import compute_contract_hash, lint_chat_request

h1 = compute_contract_hash(chat_req)
_ = lint_chat_request(chat_req)
h2 = compute_contract_hash(chat_req)
assert h1 == h2  # lint is read-only
assert chat_req is chat_req  # input object not replaced; fields unchanged
```

### 8.2 CLI

```bash
# Text report
python scripts/lint_chat_request.py path/to/chat_request.json

# Machine-readable
python scripts/lint_chat_request.py path/to/chat_request.json --json

# Print locked/open policy and exit 0
python scripts/lint_chat_request.py --policy

# CI gate: fail if severity band >= threshold
python scripts/lint_chat_request.py path/to/chat_request.json --fail-on high
python scripts/lint_chat_request.py path/to/chat_request.json --fail-on medium
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | Report printed successfully; or severity below `--fail-on` |
| `1` | File missing / invalid JSON; or severity ≥ `--fail-on` |

Default without `--fail-on` is always `0` after a successful report (report-only).

### 8.3 Agent loop opt-in (`guidance.debug`)

In `setup_turn_context` (`src/agent/loop.py`), after optional `apply_injected_business_logic`:

```text
if guidance.debug:
    report = lint_chat_request(chat_req)
    trace["catalog_lint"] = report.to_dict()
    trace["notes"].append(report.summary_line())
```

Properties:

- **Default off** — no cost on normal turns  
- **Never blocks** the turn  
- Failures are soft: `catalog_lint_failed: …` in notes  
- Runs on the **assembled** payload (rules already applied into post-brief section when present), so inventory still reads from `guidance.injections` (hash-excluded)  

Enable by setting on the catalog (open surface):

```json
"guidance": {
  "debug": true,
  "injections": { "business_logic": [ … ] }
}
```

### 8.4 Working with business logic inject APIs

Typical authoring loop:

```python
from zeus_client.zeus.catalog import inject_business_logic, apply_injected_business_logic
from zeus_client import lint_chat_request, compute_contract_hash

base = load_your_stamped_catalog()
h0 = compute_contract_hash(base)

enriched = inject_business_logic(base, {
    "entity_type": "Beer",
    "fields": ["abv"],
    "rule": "Do not process beers with abv > 7%.",
    "deny_when": {"abv": {">": 7}},
})
# still hash-stable: guidance is excluded
assert compute_contract_hash(enriched) == h0

report = lint_chat_request(enriched)
if report.severity in ("medium", "high"):
    print(report.format_text())

# At runtime the agent applies render into post-brief prompt:
ready = apply_injected_business_logic(enriched)
```

---

## 9. Files changed / added (implementation map)

| Path | Role |
|------|------|
| **`src/zeus/lint.py`** | **New.** Inventory, checkers, scoring, `ConflictReport`, `lint_chat_request`, `hash_policy_summary` |
| **`src/contract_hash.py`** | Added `HASH_EXCLUDED_ROOTS`, `HASH_EXCLUDED_STRING_MARKERS`, `LOCKED_POINTERS` (policy single source) |
| **`src/__init__.py`** | Public exports: `lint_chat_request`, `ConflictReport`, `Finding`, `hash_policy_summary` |
| **`src/agent/loop.py`** | Debug-gated lint → `trace["catalog_lint"]` + notes |
| **`scripts/lint_chat_request.py`** | **New.** CLI |
| **`tests/test_catalog_lint.py`** | **New.** Unit + CLI tests |
| **`tests/fixtures/lint_conflict_chat_request.json`** | **New.** Intentional multi-conflict fixture |
| **`tests/test_agent_loop.py`** | Coverage for debug-path catalog lint |
| **`tests/test_smoke_imports.py`** | New public symbols |
| **`README.md`** | “Lint catalog rules” section + API table row |

### Dependencies reused (not reinvented)

| Symbol | Module | Use |
|--------|--------|-----|
| `tools_from_chat_request` | `zeus.catalog` | Catalog verb names for structural checks |
| `get_mini_schema` | `zeus.catalog` | Schema orphan checks |
| `compute_contract_hash` | `contract_hash` | Tests prove lint does not change hash |
| `inject_business_logic` / `apply_injected_business_logic` | `zeus.catalog` | Existing open-rule pipeline |
| `audit_rows_against_rules` | `zeus.catalog` | Complementary **runtime** row compliance (not replaced) |

---

## 10. Fixture & expected findings

File: `tests/fixtures/lint_conflict_chat_request.json`

Intentionally includes:

| Injection | Expected checker family |
|-----------|-------------------------|
| Always prefer `find` for Beer vs never use `find` / always prefer `search` | `negation_pair` (high) |
| `deny_when abv > 7` vs `require abv >= 8` | `structured_predicate_clash` (high) |
| Two optimal_paths both `output=rows` / Beer with find vs search entry | `exclusive_preferred_tools` (medium) |
| Pipeline step `verb: teleport`, missing `as`, `return: ["find"]` | structural optimal_path_* (medium) |
| `entity_type: Wine` with brief only defining Beer | `schema_unknown_entity` (medium) |
| Duplicate free-text “Be concise…” | `duplicate_rule_text` (low) |

Typical run:

```bash
python scripts/lint_chat_request.py tests/fixtures/lint_conflict_chat_request.json
# catalog_lint: score=100 severity=high findings=8 open_rules=10
```

Bundled analytics catalog (`src/data/chat_requests/chat_request_analytics_v2.json`) is expected to stay **clean of high-severity open conflicts** (empty business_logic; structural paths are valid).

---

## 11. Testing

```bash
# Focused
pytest tests/test_catalog_lint.py tests/test_agent_loop.py tests/test_smoke_imports.py -q

# Full suite
pytest -q
```

Key assertions covered:

| Test intent | How |
|-------------|-----|
| Policy constants documented | `hash_policy_summary` / `HASH_EXCLUDED_ROOTS` / `LOCKED_POINTERS` |
| Inventory extracts open rules | fixture atom kinds |
| Multi-conflict fixture severity | score > 0, specific `check_id`s present |
| Immutability + hash stability | deepcopy equality + `compute_contract_hash` before/after |
| Clean base catalog | score 0 / none |
| Bundled analytics no high findings | no `severity == high` |
| Individual checkers | unit cases for negation, predicate, duplicate, structural |
| Score bands | `score_findings` pure unit |
| CLI text / JSON / fail-on | subprocess-style import of script `main` |
| Agent debug hook | `setup_turn_context` with `guidance.debug` sets `trace["catalog_lint"]` |
| Public exports | smoke import list |

---

## 12. Relationship to other diagnostics

| Tool | When | What it answers |
|------|------|-----------------|
| **`lint_chat_request` (ZC-35)** | Authoring / CI / debug | Are **open** rules internally inconsistent? |
| Zeus Catalog **Verify / stamp** | Publish time | Does locked content match server hash authority? |
| `compute_contract_hash` / `extract_stamped_hash` | Load / session | Hash extract + offline fingerprint |
| `run_runtime_contract_audit` | End of turn | Did bind/stamp/session match? |
| `inject_business_logic(validate=True)` | Inject time | Do entity/fields exist in MINI-SCHEMA? |
| `audit_rows_against_rules` | After tools | Did returned **rows** violate `deny_when`/`require`? |
| `guidance.debug` + LLM self-report | Turn time | AI’s **word** on which rules it applied |

These layers are complementary. A clean contract hash does **not** imply a clean conflict score, and vice versa.

---

## 13. Debugging & known limitations

| Symptom / limitation | Notes |
|----------------------|-------|
| False positive always/never | Heuristic; requires shared tokens/tools/entity. Still possible on loose wording. Treat medium/high as review prompts, not ground truth. |
| No findings but rules “feel” wrong | Locked system prompt conflicts are **not** scored in MVP. Open rules that contradict locked text need phase-2 open-vs-locked check or human review. |
| Schema checks empty | No SCOPE BRIEF / MINI-SCHEMA in the document → schema orphan checks skipped. |
| Structural checks empty | `include_structural=False`, or no `optimal_paths`. |
| Score 100 with few findings | Weights stack; two highs already reach 50; more findings cap at 100. |
| Agent has no `catalog_lint` | `guidance.debug` is false/absent (default). |
| `catalog_lint_failed` note | Exception during lint; turn continues. Inspect exception text. |
| CLI requires path | Except `--policy`, which needs no file. |
| Not a substitute for `/verify` | Linter never stamps or proves server hash match. |

### False-negative patterns (v1)

- Soft preferences without modality keywords (“it is better if…”)  
- Conflicts split across locked instructions + open guidance  
- Semantic opposites without shared lexical tokens  
- Multi-hop logical contradictions beyond simple deny/require interval math  

---

## 14. Integration recipes

### CI gate on operator catalogs

```bash
# Fail build if open-rule conflicts are medium or worse
python scripts/lint_chat_request.py "$CATALOG_PATH" --fail-on medium
```

### Pre-commit / local author loop

```bash
python scripts/lint_chat_request.py ~/.config/zeus_client/chat_requests/beer-sample__default/chat_request_analytics_v2.json
```

### Host app debug panel

```python
report = lint_chat_request(chat_req)
if report.finding_count:
    ui.show_banner(report.summary_line())
    ui.show_json(report.to_dict())
```

When using `run_agent` with `guidance.debug`, read `trace["catalog_lint"]` from the turn result without a separate call.

### After sync

```python
from zeus_client import sync_chat_requests, lint_chat_request
from zeus_client.zeus.catalog import chat_request_path
import json

await sync_chat_requests(cfg)
path = chat_request_path("v2", mode, bucket, scope)
doc = json.loads(path.read_text())
print(lint_chat_request(doc).format_text())
```

---

## 15. Phase 2 / follow-ons (not implemented)

Documented so future work does not reopen MVP design without intent:

1. **LLM-assisted contradiction review** — structured findings; still must not auto-edit locked blocks  
2. **Soft cap / warn-before-session** if score exceeds a threshold  
3. **Open-vs-locked informational cross-check** — flag open rules that may contradict hashed `system_prompt` text (read-only)  
4. **Workbench / chat-trace UI** rendering of `ConflictReport` JSON  
5. **Richer optimal_path exclusivity** (embedding / intent classifiers instead of token + intent_pattern heuristics)  

---

## 16. Quick reference

```python
from zeus_client import (
    lint_chat_request,      # main API
    ConflictReport,        # result type
    Finding,               # one issue
    hash_policy_summary,   # locked vs open docs as dict
    compute_contract_hash, # prove lint does not drift hash
)
```

```bash
python scripts/lint_chat_request.py FILE.json
python scripts/lint_chat_request.py FILE.json --json
python scripts/lint_chat_request.py FILE.json --fail-on high
python scripts/lint_chat_request.py --policy
pytest tests/test_catalog_lint.py -q
```

```json
"guidance": {
  "debug": true,
  "injections": {
    "business_logic": [
      {"id": "r1", "rule": "…", "entity_type": "Beer", "fields": ["abv"], "deny_when": {"abv": {">": 7}}}
    ]
  },
  "optimal_paths": [ … ]
}
```

---

## 17. Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-07-15 | agent | Initial ZC-35 implementation + this guide: `lint.py`, CLI, policy constants, debug trace hook, fixtures/tests, README section |
