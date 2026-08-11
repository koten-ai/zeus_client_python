# Zeus Client Python V2 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
> **Branch:** `feat/V2` (already created + tracking `origin/feat/V2` @ `792aad8`)
> **Mode:** **update** of existing package `kotenai-zeus-client` → major **2.0** (not greenfield repo)

**Goal:** Rebuild `kotenai-zeus-client` as the V2 **journaled hexagonal runtime** (Candidate B), porting proven **0.3.1** behavioral oracles, while following design-repo **HOW_TO_MAKE_A_CLIENT** law (Agent + Direct, offline candidate honesty, no forged stamps).

**Architecture:** Domain use-cases over ports; HTTP/LLM/Hub/FS as adapters; every meaningful action appends an immutable **Execution Journal**. Detective, session-trace multi-hop, OTLP, and public timeline are **projectors**. Public DX is `ZeusRuntime` + typed `TurnResult` / `VerbResult` — not a mutable `trace` dict and not a rewrite-in-place of `loop.py`.

**Tech Stack:** Python ≥3.11 · httpx · pytest/pytest-asyncio · respx · optional pydantic v2 for config only · ruff + mypy/pyright · design suite `conformance-0.2-dev`

**Sources of truth (conflict order):**
1. Family law: `../zeus_client_design/HOW_TO_MAKE_A_CLIENT.md` + guides/api + kit specs
2. Python product architecture: `docs/V2/DESIGN.md` + `docs/V2/IMPLEMENTATION_GUIDE.md` (IG wins layout/phase)
3. Product backlog: `../zeus_client_design/MICHAEL_WISHLIST.md` (`ZCM-WISH-*`) + `docs/MICHAEL/`
4. Wire field names: `../Zeus/docs/openapi.yaml` wins over design `wire/` samples
5. Behavioral oracles: current `src/` + `tests/` 0.3.1 (semantics to preserve, not structure to extend)
6. BASE packs: latest non-prototype under Zeus vendor path `Zeus/ai/zeus_chat_request/v2/base/` (e.g. `base-6.2`); floor wire freeze still base-5 family

---

## Current context / assumptions

| Fact | Value |
| --- | --- |
| Package today | `0.3.1` — free functions + thin `ZeusClient`; mutable `trace`; verbs/search/session-hops/peel shipped |
| V2 code | **Not implemented** — design docs only under `docs/V2/` |
| Branch | `feat/V2` clean @ main tip |
| Pins file | **Missing** — need `sdk_bootstrap.pins.json` |
| Sibling design | `/home/michael/koten-ai/zeus_client_design` present |
| Zeus engine + OpenAPI | `/home/michael/koten-ai/Zeus` present (`docs/openapi.yaml`) |
| chat_request | Vendored under `Zeus/ai/zeus_chat_request` (base-5…base-6.2); standalone sibling optional |
| Layout today | `package-dir = {"zeus_client" = "src"}` — flat modules under `src/` |
| Claim bar (train) | Offline **candidate** / alpha spine first; never self-award MATRIX `supported` |
| Modes in scope | **Agent + Direct** only; multi_agent=no; plugins=no |
| Live Zeus/LLM | Optional after offline green; do not block Phases 0–7 |
| Packaging constraint | Keep import name `zeus_client` / PyPI `kotenai-zeus-client`; bump to `2.0.0aN` during build |

### Dual-tree strategy (locked)

Do **not** delete 0.3.1 until Phase 8 cutover.

```text
src/                         # KEEP 0.3.1 tree importable as zeus_client.* during alpha
  ...existing modules...

src_v2/zeus_client/          # NEW V2 tree (preferred during alpha to avoid import collisions)
  runtime.py
  api/
  domain/
  application/
  ports/
  adapters/
  config/
  security/
  compat/

# Alternative if implementer prefers single root later:
# move 0.3.1 → src/zeus_client/v1_legacy/ and put V2 at src/zeus_client/
# Decision for Phase 0 Task: prefer src_v2/ + setuptools package-dir dual mapping
# so `import zeus_client` stays V1 until explicit cutover flag / major bump publish.
```

**Recommended alpha packaging:**

- V1 remains default `import zeus_client` (0.3.1 demos keep working).
- V2 importable as `zeus_client_v2` **or** `zeus_client.v2` during alpha.
- At Phase 8 GA: swap default package to V2; leave `zeus_client.compat.v1` shims ≤1 minor.

**IG note:** IG says greenfield under `src/zeus_client/`. For this monorepo with live demos on 0.3.1, **dual package path is safer**. Document choice in README badge “V2 in progress”.

### HOW_TO phase ↔ V2 IG phase map

| HOW_TO | Golden G | V2 IG | Primary ZCM |
| --- | --- | --- | --- |
| G0 pins + scaffold | G0 | Phase 0 | — |
| P-HTTP + P-Auth | G1 | Phase 2–3 ports/adapters | 003, 008, 009 |
| P-Direct | G3 | Phase 3 | 004, 012 |
| P-Catalog | G2 | Phase 4 | 010, 029 |
| P-Session | G4 | Phase 5 | 006, 007 |
| P-LLM | G7 | Phase 6 (+ unit classify) | 008, 024 |
| P-Agent + P-Control | G5–G6 | Phase 6 | 011, floor-5 law |
| P-Obs | — | Phase 1 + 7 + 8 | 001, 009, 035 |
| Detective projector | — | Phase 7 | 005, 007, 020 |
| P-Suite | G8 | After Phase 6+ adapter | family ZCF suite |
| P-Release | — | Phase 8 | GA 2.0.0 |

**Default stop for first shippable train:** IG Phases **0–7** green offline (Pri-1 ZCM-001…012 + detective) + unit oracles; claim **`2.0.0b1` candidate**. Phase 8 GA separate.

---

## Hard rules (fail closed — copy into every PR)

1. Never invent production `contract_hash` / Hub stamps.
2. Do not rewrite `src/agent/loop.py` into a god module — port via tests as oracles.
3. Domain modules must not import `httpx` or provider SDKs.
4. No process-global HTTP/auth on V2 paths.
5. No new tuple public returns — typed results only.
6. G2 / jailbreak scores / `wish_i_knew` never in user-facing `answer`.
7. No public `run_pipeline` / `rt.data.pipeline`.
8. Catalog resolve: scope dir → non-scope general → bundled; **no** silent sibling `*__*` rglob.
9. Typeahead = Direct only (`rt.data.search`); never agent per keystroke.
10. Secrets only via env / SecretStore; redact at journal boundary.
11. Detective/session-trace projectors never raise out of a successful domain turn.
12. Claim honesty: `candidate`/`partial` until suite required cases green.
13. Do not dual-list ZCF/ZC items as new ZCM IDs.
14. Three clocks independent: Zeus engine · BASE `base-N` · package semver.

---

## Proposed approach

1. **Bootstrap honesty** (HOW_TO G0): pins, claim text, dual-tree skeleton, smoke tests.
2. **Spine first** (IG 1–2): journal, errors, redact, Runtime, ports, config profiles.
3. **Data plane before agent** (IG 3): verbs + typeahead with journaled hops (HOW_TO P-Direct / G3).
4. **Catalog fail-closed + hash oracles** (IG 4 / G2) using 0.3.1 test vectors.
5. **Session + multi-hop projector** (IG 5 / G4) before agent commit path.
6. **LLM + agent turn + control plane** (IG 6 / G5–G6) with fake ports; peel + policy + `ai_process_result`.
7. **Detective + debug + transport replay** (IG 7).
8. **Conformance adapter** (HOW_TO P-Suite) offline against design suite.
9. **Harden + V1 compat + GA** (IG 8) only after beta oracles + demo migration notes.

**TDD:** every domain/projector task = failing test → minimal code → pass → commit.

**Oracle porting:** Prefer copying **assertions and fixtures** from:
- `tests/test_contract_hash.py`
- `tests/test_prompt_inject_hash_stable.py`
- `tests/test_catalog_sync.py`
- `tests/test_zeus_suggest.py` / `test_zeus_verbs.py`
- `tests/test_session_hops.py` / `test_agent_session_phase.py`
- `tests/test_layer_a.py` / `test_policy_table.py` / `test_agent_loop.py` / `test_agent_tool_round.py`

---

## Files likely to change (train-wide)

### Create (V2 tree — illustrative; follow IG §0)

```text
sdk_bootstrap.pins.json
src_v2/zeus_client/__init__.py
src_v2/zeus_client/py.typed
src_v2/zeus_client/runtime.py
src_v2/zeus_client/api/{__init__,agent,data,catalog,debug}.py
src_v2/zeus_client/domain/{ids,errors,contract,catalog,layer_a,policy,messages}.py
src_v2/zeus_client/domain/journal/{__init__,events,journal,spans,export,payload_store}.py
src_v2/zeus_client/application/{agent_turn,data_verb,typeahead,catalog_sync,session_lifecycle,middleware,plugins,control_plane_inject}.py
src_v2/zeus_client/application/detective/{__init__,build,overview,prompt_checklist,diagnosis,playbooks,support_pack,extract,hub_hydrate}.py
src_v2/zeus_client/application/projectors/{__init__,session_trace,public_trace}.py
src_v2/zeus_client/ports/{zeus,llm,hub_debug,catalog_store,secrets,clock,id_factory,http}.py
src_v2/zeus_client/adapters/zeus_http/{__init__,auth,session,verbs,catalog_remote,headers}.py
src_v2/zeus_client/adapters/llm_openai_compatible/{__init__,client}.py
src_v2/zeus_client/adapters/hub_debug_http/{__init__,client}.py
src_v2/zeus_client/adapters/catalog_fs/{__init__,store}.py
src_v2/zeus_client/adapters/secrets_env/{__init__,store}.py
src_v2/zeus_client/adapters/otlp/{__init__,exporter}.py   # Phase 8 optional
src_v2/zeus_client/config/{models,loader,profiles}.py
src_v2/zeus_client/security/{redact,validate}.py
src_v2/zeus_client/compat/__init__.py
src_v2/zeus_client/compat/v1/…                          # Phase 8
tests/unit/domain/…
tests/unit/application/…
tests/contract/adapters/…
tests/integration/…
tests/fixtures/v2/…
conformance/adapter/python/…                            # or tests/conformance/
docs/V2/MIGRATION.md                                    # Phase 8
BLOCKED.md                                              # if clones/suite residuals
config.example.json                                     # V2-shaped, no secrets
```

### Modify

- `pyproject.toml` — dual package discovery, version `2.0.0a0+`, dev deps (ruff/mypy optional)
- `README.md` — V2-in-progress badge; claim candidate; link HOW_TO + CHECKLIST + COMPAT
- `docs/V2/README.md` — status → implementing on `feat/V2`
- Optionally keep 0.3.1 `src/` untouched until Phase 8

### Do not touch early

- demo_yelp / chat-trace until Phase 8 migration notes
- Production stamped catalogs (never hand-write hashes)
- zeus_chat_request `CURRENT.json`

---

## Step-by-step plan

### Task 0.1: Pins + claim scaffold (HOW_TO G0)

**Objective:** Language-repo bootstrap honesty without secrets.

**Files:**
- Create: `sdk_bootstrap.pins.json`
- Modify: `README.md` (claim section)
- Optional: `BLOCKED.md` stub

**Step 1:** Copy design pins template and set Python fields:

```json
{
  "language": {
    "id": "python",
    "package_name": "kotenai-zeus-client",
    "module_path": "zeus_client",
    "min_runtime": "3.11",
    "greenfield": false
  },
  "claim": {
    "client_floor": "client-floor-5",
    "claim_level": "candidate",
    "modes": ["agent", "direct"],
    "multi_agent": "no",
    "plugins": "no"
  },
  "suite": {
    "suite_version": "conformance-0.2-dev",
    "design_repo_ref": "local:../zeus_client_design",
    "required_levels": ["L0", "L1", "L2"],
    "detective_tapes_min": ["smooth_short", "fail_zeus"]
  },
  "catalog": {
    "offline_mock_path": "../zeus_client_design/fixtures/catalogs/mock_base5_minimal",
    "mock_base_id": "base-5-mock",
    "production_base_id": null
  },
  "zeus": {
    "engine_semver_range": "0.6.x",
    "openapi_path": "../Zeus/docs/openapi.yaml",
    "default_base_url": "http://127.0.0.1:8080",
    "live_smoke": false
  },
  "llm": {
    "provider": "xai",
    "base_url": "https://api.x.ai/v1",
    "model": "grok-4-1-non-reasoning",
    "api_key_env": "XAI_API_KEY",
    "context_window_tokens": 128000,
    "context_soft_limit": 0.8,
    "ai_process_result_default": false
  },
  "stamps": { "user": "zeus_client", "version_from": "package_semver" }
}
```

Note: package product default for `ai_process_result` remains **True** (Hub parity) in runtime settings; pins product default **false** is for cheap-product guidance — document both (0.3.1 lesson).

**Step 2:** README states claim_level **candidate**, modes agent+direct, links to design HOW_TO / CHECKLIST / MATRIX / COMPAT. No “supported”.

**Step 3:** Commit

```bash
git add sdk_bootstrap.pins.json README.md
git commit -m "chore(v2): bootstrap pins + candidate claim (G0)"
```

---

### Task 0.2: Dual-tree package skeleton + smoke (IG Phase 0)

**Objective:** Importable V2 package with `py.typed` and empty modules; CI-capable smoke.

**Files:**
- Create: `src_v2/zeus_client/**` package tree (empty modules + `__init__.py`)
- Create: `tests/unit/test_smoke_import_v2.py`
- Modify: `pyproject.toml`

**Step 1: Failing smoke test**

```python
# tests/unit/test_smoke_import_v2.py
def test_v2_version_and_runtime_importable():
    import zeus_client_v2 as zc
    assert zc.__version__.startswith("2.")
    from zeus_client_v2.runtime import ZeusRuntime  # may be stub
    assert ZeusRuntime is not None
```

**Step 2:** Run `pytest tests/unit/test_smoke_import_v2.py -v` → FAIL (module missing)

**Step 3: Minimal packaging**

`pyproject.toml` additions (illustrative):

```toml
version = "2.0.0a0"   # only when cutting over default package; during dual-tree keep 0.3.1
# Better dual approach:
# - leave project.version at 0.3.1 until cutover OR use 2.0.0a0 with V1 still importable
# Prefer: version = "2.0.0a0" on feat/V2 with explicit note demos pin 0.3.1 from main

[tool.setuptools]
package-dir = {"zeus_client" = "src", "zeus_client_v2" = "src_v2/zeus_client"}
packages = [
  "zeus_client", "zeus_client.agent", "zeus_client.llm", "zeus_client.trace", "zeus_client.zeus",
  "zeus_client_v2", "zeus_client_v2.api", "zeus_client_v2.domain", "zeus_client_v2.domain.journal",
  "zeus_client_v2.application", "zeus_client_v2.application.detective",
  "zeus_client_v2.application.projectors", "zeus_client_v2.ports",
  "zeus_client_v2.adapters", "zeus_client_v2.adapters.zeus_http",
  "zeus_client_v2.adapters.llm_openai_compatible", "zeus_client_v2.adapters.hub_debug_http",
  "zeus_client_v2.adapters.catalog_fs", "zeus_client_v2.adapters.secrets_env",
  "zeus_client_v2.config", "zeus_client_v2.security", "zeus_client_v2.compat",
]
```

```python
# src_v2/zeus_client/__init__.py
__version__ = "2.0.0a0"
__all__ = ["__version__"]
```

Create empty packages matching IG layout; `runtime.py` stub class `ZeusRuntime`.

**Step 4:** `pip install -e ".[dev]"` && `pytest tests/unit/test_smoke_import_v2.py -v` → PASS  
Also: full `pytest -q` must still pass (V1 unbroken).

**Step 5:** Commit `chore(v2): Phase 0 dual-tree skeleton + smoke`

---

### Task 1.1: Domain IDs + ErrorCode taxonomy (IG Phase 1 · ZCM-008)

**Objective:** Typed IDs and error taxonomy with retryable flags.

**Files:**
- Create: `src_v2/zeus_client/domain/ids.py`, `domain/errors.py`
- Test: `tests/unit/domain/test_errors.py`, `test_ids.py`

**Step 1: Failing tests** — ErrorCode enum includes family LLM codes `050010`–`050018` mapping (rate vs quota vs context); `ZeusClientError` has `code`, `retryable`, `component`, `public_message`.

**Step 2:** Implement minimal frozen exceptions + newtype/str wrappers (`TurnId`, `ChatId`, `CallId`, `SessionId`, `ReqId`).

**Step 3:** `pytest tests/unit/domain/test_errors.py tests/unit/domain/test_ids.py -q` PASS

**Step 4:** Commit `feat(v2): domain ids + ErrorCode taxonomy`

---

### Task 1.2: Redactor (IG Phase 1 · ZCM-009)

**Objective:** Secrets never enter journal bodies.

**Files:**
- Create: `src_v2/zeus_client/security/redact.py`
- Test: `tests/unit/domain/test_redact_headers.py`, `test_redact_json_nested.py`

**Assert:** masks `Authorization`, `password`, `api_key`, bearer tokens; nested JSON keys; text max_chars previews.

**Commit:** `feat(v2): redaction at boundary`

---

### Task 1.3: PayloadStore + ExecutionJournal + spans (IG Phase 1 · ZCM-001)

**Objective:** Append-only journal with content-addressed payloads and span linkage.

**Files:**
- Create: `domain/journal/{events,journal,spans,payload_store,export}.py`
- Test: `test_journal_append_order`, `test_payload_ref_dedup`, `test_export_schema_v1`, `test_span_parent_linkage`

**Minimal event types:** `turn.started`, `turn.completed`, `span.started`, `span.ended`, `error.raised`, `note`, later `zeus.hop`, `llm.round`.

```python
@dataclass(frozen=True, slots=True)
class JournalEvent:
    event_id: str
    ts_ms: int
    type: str
    component: str
    turn_id: str
    span_id: str | None
    parent_span_id: str | None
    data: Mapping[str, Any]  # already redacted
    payload_refs: tuple[str, ...] = ()
```

**Rules:** hot path stores hashes/previews + `payload_ref`; export `journal_schema: 1`.

**Commit:** `feat(v2): immutable ExecutionJournal + payload store`

---

### Task 2.1: RuntimeConfig + profiles + SecretStore (IG Phase 2 · ZCM-025, 040)

**Objective:** Immutable config after bind; env overrides; profiles dev/prod/ci.

**Files:**
- Create: `config/models.py`, `loader.py`, `profiles.py`
- Create: `adapters/secrets_env/store.py`
- Create: `config.example.json` (no secrets)
- Test: loader tmp paths; profile matrix; config `__repr__` redacts secrets

**Locked fields (minimum):** Zeus URL, DataTarget (bucket/scope/collection), auth mode, LLM provider block (`api_key_env` name only), `ClientSettings` (`ai_process_result` default **True** in package), `RetryPolicy`, `RedactionPolicy`, `DebugPolicy`.

**Commit:** `feat(v2): RuntimeConfig + profiles + secrets env`

---

### Task 2.2: Ports protocols + ZeusRuntime wiring (IG Phase 2 · ZCM-002, 003)

**Objective:** `ZeusRuntime` async CM wires fakes; closes resources; no global HTTP.

**Files:**
- Create: `ports/*.py` Protocols (`ZeusPort`, `LlmPort`, `CatalogStorePort`, `HubDebugPort`, `SecretStorePort`, `Clock`, `IdFactory`, `HttpPort`)
- Create: `runtime.py` — `from_config`, override injection, `_Services` bundle
- Create: `api/__init__.py` facade properties stubs
- Test: lifecycle with fake ports; pool close on exit

```python
async with ZeusRuntime.from_config(path=None, profile="development") as rt:
    assert rt.config.zeus.url
```

**Commit:** `feat(v2): ZeusRuntime + ports wiring`

---

### Task 3.1: Zeus HTTP headers + auth + verb dispatch (IG Phase 3 · HOW_TO P-HTTP/P-Auth/P-Direct · G1/G3 · ZCM-012)

**Objective:** Real `ZeusPort` over httpx; every hop journals `zeus.hop` with `req_id`; mode header always set.

**Files:**
- Create: `adapters/zeus_http/{headers,auth,verbs}.py`
- Create: `application/data_verb.py`, `api/data.py`
- Domain: verb result types
- Test: respx contract per verb URL shape; pipeline rejected on public API; 4xx/5xx still capture `X-Zeus-Req-Id`

**Locked:**
- Capture Zeus-minted `req_id` or UUID v4 pre-mint only
- Product stamp `user=zeus_client` + package version
- Public API: `rt.data.verb/find/get/...` + `search_verb`; **no** pipeline
- Auth: none/basic/bearer/session; never log tokens

**Oracle:** port URL matrix + `EXPOSED_V2_VERBS` from `src/zeus/verbs.py` / `tests/test_zeus_verbs.py` / `test_zeus_dispatch.py`.

**Commit:** `feat(v2): Zeus HTTP adapter + data verb use-case`

---

### Task 3.2: Typeahead use-case (IG Phase 3 · ZCM-012, 031)

**Objective:** `rt.data.search` FTS defaults; optional N1QL only when configured; merge_hits oracle.

**Files:**
- Create: `application/typeahead.py`
- Test: port `tests/test_zeus_suggest.py` behaviors

**Locked:** no implicit host:8093; FTS default not hybrid; naming `search` not `fast_suggest` for new APIs.

**Commit:** `feat(v2): typeahead search use-case`

---

### Task 4.1: Contract hash oracles (IG Phase 4 · HOW_TO P-Catalog) ✅

**Status:** Done — `d8e0c6e` · Jira ZCP-11 Done · 21 unit + 508 full pytest

**Objective:** Port V1 hash/stamp/heal/session resolve algorithms with golden vectors.

**Files:**
- Create: `domain/contract.py`
- Test: port vectors from `tests/test_contract_hash.py`

**Never forge production stamps in fixtures labeled prod.**

**Commit:** `feat(v2): contract hash domain (oracle port)`

---

### Task 4.2: Catalog FS fail-closed + sync preserve (IG Phase 4 · ZCM-010 · G2) ✅

**Status:** Done — see latest `feat/V2` commit · Jira ZCP-12

**Objective:** Path resolution without sibling-scope rglob; sync preserve local consistent stamps.

**Files:**
- Create: `domain/catalog.py`, `adapters/catalog_fs/store.py`, `adapters/zeus_http/catalog_remote.py`, `application/catalog_sync.py`, `api/catalog.py`
- Test: sibling scope must **not** win; port `test_catalog_sync.py`; mock load from design `fixtures/catalogs/mock_base5_minimal`

**Path order (locked):**
1. `{CHAT_REQUESTS_DIR}/{bucket}__{scope}/chat_request_{mode}_v2.json`
2. `{CHAT_REQUESTS_DIR}/chat_request_{mode}_v2.json` (non-scope only)
3. Bundled package data
4. Else loud `CatalogError`

**Commit:** `feat(v2): catalog fail-closed load + sync`

---

### Task 4.3: Control-plane inject hash-stable (IG Phase 4) ✅

**Status:** Done — hash-stable inject on `feat/V2` · Jira ZCP-13

**Objective:** Inject rules/settings/output_request only after `## SCOPE BRIEF` / `## MINI-SCHEMA`; hash unchanged.

**Files:**
- Create: `application/control_plane_inject.py`
- Test: port `tests/test_prompt_inject_hash_stable.py`

**Commit:** `feat(v2): hash-stable control-plane inject`

---

### Task 5.1: Session lifecycle adapter (IG Phase 5 · HOW_TO P-Session · G4) ✅

**Status:** Done — `feat/V2` · Jira ZCP-14

**Objective:** create / rehydrate / continue / dead-sid recovery; server-minted session id only.

**Files:**
- Create: `adapters/zeus_http/session.py`, `application/session_lifecycle.py`
- Models: `SessionHandle` frozen
- Test: respx against design wire `v2_session_*.json` shapes; dead sid recreate same turn

**Commit:** `feat(v2): session lifecycle`

---

### Task 5.2: Session-trace multi-hop projector (IG Phase 5 · ZCM-006) ✅

**Status:** Done — `feat/V2` · Jira ZCP-15

**Objective:** Rehome 0.3.1 aggregate algorithm as pure projector over journal hops.

**Files:**
- Create: `application/projectors/session_trace.py`
- Test: port `tests/test_session_hops.py` oracles

**Algorithm (locked):**

```text
hops = zeus.hop events with req_id this turn
primary = rank(error > rows > find/search > non-pipeline)
payload = build_aggregate(hops, primary, layer_a?, snippets max 2000)
for req_id in secondary_first_then_primary:
    POST /v2/session/trace identical body
journal projector.session_trace outcome (soft-fail)
```

**Commit:** `feat(v2): session-trace multi-hop projector`

---

### Task 6.1: LLM adapter + error classify (IG Phase 6 · HOW_TO P-LLM · G7)

**Objective:** OpenAI-compatible adapter; rate vs quota vs context classification; no key logging.

**Files:**
- Create: `adapters/llm_openai_compatible/client.py`
- Test: table-driven 429 bodies → `050010` vs `050011`; context → `050013`; RetryBudget only retryable

**Read:** design `docs/ai_api/FAMILY_LLM_ERRORS.md`, `CONTEXT_WINDOWS.md`

**Commit:** `feat(v2): LLM adapter + error classification`

---

### Task 6.2: Layer A + policy domain (IG Phase 6 · HOW_TO P-Control · G6 · ZCM-011)

**Objective:** Required-four validation, peel, policy table, G2 quarantine.

**Files:**
- Create: `domain/layer_a.py`, `domain/policy.py`
- Test: port `test_layer_a.py`, `test_policy_table.py`; answer never contains scores/wish dumps

**Public peel helpers remain available for demos.**

**Commit:** `feat(v2): Layer A + policy domain`

---

### Task 6.3: Agent turn use-case + middleware (IG Phase 6 · HOW_TO P-Agent · G5 · ZCM-004)

**Objective:** Full turn over ports; cheap vs insight; force return; typed `TurnResult`.

**Files:**
- Create: `application/agent_turn.py`, `middleware.py`, `plugins.py`, `api/agent.py`, `projectors/public_trace.py`
- Test: fake LlmPort + ZeusPort scripted dialogues; port loop/tool_round semantics; `ai_process_result` matrix

**Loop law (locked):**

```text
setup journal + auth + catalog + session
loop rounds:
  llm.complete
  tool_calls → zeus hops (pipeline allowed inside agent only) → append truncated tools
  terminate (return | pipeline turn_complete) → break
post-tool: insight if ai_process_result else cheap
policy + peel → answer
commit session + projectors
return TurnResult
```

```python
@dataclass(frozen=True)
class TurnResult:
    answer: str
    status: TurnStatus
    structured: StructuredResult | None
    session: SessionHandle | None
    debug: DebugBundle
    error: ErrorInfo | None
    messages: tuple[Message, ...]
```

**Commit:** `feat(v2): agent turn use-case + middleware`

---

### Task 7.1: Detective projector (IG Phase 7 · ZCM-005, 007)

**Objective:** Overview · Diagnosis · Prompt pure from journal; kill-switch; soft-fail.

**Files:**
- Create: `application/detective/*`, attach on `DebugBundle`
- Test: golden fixtures; never raises on ok turn; G2 not in answer

**Schema v1 keys:** `version`, `source`, `hub_hydrated`, `overview`, `prompt`, `diagnosis`

**Playbooks v1 min:** boundary_collections, missing_inject, hybrid_empty_find_ok, project_dotted_fk, tool_errors, hollow_answer, contract_drift

**Kill-switch:** `DebugPolicy.detective_briefing=False` or `ZEUS_CLIENT_DETECTIVE=0`

**Commit:** `feat(v2): Client Detective briefing projector`

---

### Task 7.2: Debug API + transport replay (IG Phase 7 · ZCM-020, 022)

**Objective:** export journal, span tree, transport replay offline.

**Files:**
- Create: `api/debug.py`, `application/replay.py`
- Test: replay event-type sequence greentest; export redacted

**Commit:** `feat(v2): debug export + transport replay`

---

### Task S.1: Conformance adapter offline (HOW_TO P-Suite · G8)

**Objective:** Run design suite required cases against V2 runtime with mocks.

**Files:**
- Create: adapter under `tests/conformance/` implementing design `ADAPTER_CONTRACT.md`
- Emit report JSON per schema
- Pin `suite_version` in pins + release notes

**Minimum cases:**
- `L0.catalog.load_mock.001`
- `L1.loop.single_tool_return.001`
- `L2.policy.matrix.001` / `L2.layer_a.required_four.001` best-effort for candidate
- Detective `assert_only` smooth_short + fail_zeus family

**Run design reference first:**

```bash
python3 ../zeus_client_design/conformance/adapter/reference/run_suite.py
```

**Do not** invent full Hub rewind dumps; kit-β residual → `BLOCKED.md`.

**Commit:** `test(v2): conformance adapter offline candidate`

---

### Task 8.x: Hardening + compat + GA (IG Phase 8) — separate train after beta

**Objectives (summary, not day-one):**
- `compat/v1` shims for `run_agent` / `run_search` / `run_verb` with DeprecationWarning
- Remove dual-tree; default `import zeus_client` = V2
- `docs/V2/MIGRATION.md` + demo_yelp notes
- Optional OTLP extra; metrics counters; typeahead rate limit
- Security review vs `docs/V2/SECURITY.md`
- Version `2.0.0`; update design MATRIX row (follow-up PR on design repo)
- Mark ZCM statuses in MICHAEL_WISHLIST when shipped

**Out of default alpha:** plugins, multi-agent jobs, semantic_cache product claims, live smoke CI.

---

## Tests / validation (standing commands)

```bash
# Always after each task
cd /home/michael/koten-ai/zeus_client_python
.venv/bin/pytest -q                                 # V1 must stay green during dual-tree
.venv/bin/pytest tests/unit -q                       # V2 units
.venv/bin/pytest tests/contract -q                   # when adapters exist

# Targeted oracles when porting
.venv/bin/pytest tests/test_contract_hash.py tests/test_prompt_inject_hash_stable.py -q
.venv/bin/pytest tests/test_session_hops.py tests/test_zeus_suggest.py tests/test_zeus_verbs.py -q

# Design suite reference (offline)
python3 ../zeus_client_design/conformance/adapter/reference/run_suite.py

# Optional later live (never default CI)
# pins.live_smoke=true + ZEUS up + XAI_API_KEY — see design docs/ops/LIVE_SMOKE.md
```

**Version sync:** `pyproject.toml` version == package `__version__` every release cut.

**Done definition per phase:** IG milestone checkboxes + corresponding ZCM acceptance one-liners.

---

## Ship bands (when to stop)

| Band | Includes | Version claim |
| --- | --- | --- |
| **Alpha spine** | Tasks 0–6.3 + 5.2 (ZCM-001…012 minus full detective polish) | `2.0.0aN` internal |
| **Beta ops** | Task 7.x + S.1 + replay | `2.0.0b1` **candidate** offline |
| **GA** | Task 8.x + demo migration + MATRIX honesty | `2.0.0` only after suite required + human |

Default agent stop after **Beta candidate** unless human expands.

---

## Risks, tradeoffs, open questions

| Risk | Mitigation |
| --- | --- |
| Dual-tree / import confusion | Clear package name `zeus_client_v2`; README badge; single cutover PR in Phase 8 |
| Porting oracles lose subtle loop behavior | Prefer behavioral fixtures over line-by-line copy; keep V1 tests green as reference |
| Hash algorithm drift | Freeze golden vectors from V1 tests; no “improvements” without fixture update |
| Scope creep (OTLP, streaming, CEL policy) | Pri-3/4 explicitly out of alpha |
| Conformance adapter incomplete kit | Honest `BLOCKED.md`; claim candidate not supported |
| `ai_process_result` pin false vs package true | Document both; do not silently flip package default |
| setuptools package list drift | Prefer `find` config or generate list in Phase 0 carefully |
| Demo breakage if version bumps early | Keep V1 default import until Phase 8; demos stay on main/0.3.1 |

**Open questions (implementer defaults if unanswered):**
1. Dual import name: **`zeus_client_v2`** (default this plan) vs nested `zeus_client.v2`.
2. When to bump default PyPI version on the branch: **2.0.0a0 immediately on feat/V2** vs keep 0.3.1 until cutover — prefer **2.0.0a0 on branch** with demos still depending on main/path.
3. Whether conformance adapter lives in-package or only under `tests/` — prefer `tests/conformance` until green, then optional console script.

---

## Execution notes for subagents

- Work only on `feat/V2`; do not force-push; commit after each task.
- Read `docs/V2/IMPLEMENTATION_GUIDE.md` for the phase being implemented before coding.
- Read matching HOW_TO phase + API guide page for wire law.
- If blocked on missing clone/fixture: write `BLOCKED.md`, do not invent goldens.
- Append traps to design `HOW_TO_MAKE_A_CLIENT_LESSON_LEARNED.md` only when a real new trap is found (separate design-repo commit/PR).
- After Pri-1 items ship, update **status** in design `MICHAEL_WISHLIST.md` (design repo PR) — do not renumber IDs.

---

## Jira tickets (project ZCP · zeus_client_python)

Board: https://kotenai.atlassian.net/browse/ZCP-1

| Plan task | Jira | Summary |
| --- | --- | --- |
| Epic | [ZCP-1](https://kotenai.atlassian.net/browse/ZCP-1) | V2 journaled hexagonal runtime |
| 0.1 | [ZCP-2](https://kotenai.atlassian.net/browse/ZCP-2) | Pins + claim scaffold (G0) |
| 0.2 | [ZCP-3](https://kotenai.atlassian.net/browse/ZCP-3) | Dual-tree skeleton + smoke |
| 1.1 | [ZCP-4](https://kotenai.atlassian.net/browse/ZCP-4) | Domain IDs + ErrorCode |
| 1.2 | [ZCP-5](https://kotenai.atlassian.net/browse/ZCP-5) | Redactor |
| 1.3 | [ZCP-6](https://kotenai.atlassian.net/browse/ZCP-6) | ExecutionJournal + payloads |
| 2.1 | [ZCP-7](https://kotenai.atlassian.net/browse/ZCP-7) | RuntimeConfig + profiles |
| 2.2 | [ZCP-8](https://kotenai.atlassian.net/browse/ZCP-8) | Ports + ZeusRuntime |
| 3.1 | [ZCP-9](https://kotenai.atlassian.net/browse/ZCP-9) | Zeus HTTP + data verbs |
| 3.2 | [ZCP-10](https://kotenai.atlassian.net/browse/ZCP-10) | Typeahead search |
| 4.1 | [ZCP-11](https://kotenai.atlassian.net/browse/ZCP-11) | Contract hash oracles |
| 4.2 | [ZCP-12](https://kotenai.atlassian.net/browse/ZCP-12) | Catalog fail-closed + sync |
| 4.3 | [ZCP-13](https://kotenai.atlassian.net/browse/ZCP-13) | Hash-stable inject |
| 5.1 | [ZCP-14](https://kotenai.atlassian.net/browse/ZCP-14) | Session lifecycle |
| 5.2 | [ZCP-15](https://kotenai.atlassian.net/browse/ZCP-15) | Session-trace projector |
| 6.1 | [ZCP-16](https://kotenai.atlassian.net/browse/ZCP-16) | LLM adapter + classify |
| 6.2 | [ZCP-17](https://kotenai.atlassian.net/browse/ZCP-17) | Layer A + policy |
| 6.3 | [ZCP-18](https://kotenai.atlassian.net/browse/ZCP-18) | Agent turn + middleware |
| 7.1 | [ZCP-19](https://kotenai.atlassian.net/browse/ZCP-19) | Detective + DebugBundle |
| 7.2 | [ZCP-20](https://kotenai.atlassian.net/browse/ZCP-20) | Debug API + transport replay |
| S.1 | [ZCP-21](https://kotenai.atlassian.net/browse/ZCP-21) | Conformance adapter offline |
| 8.x | [ZCP-22](https://kotenai.atlassian.net/browse/ZCP-22) | Hardening + compat + GA |


## Quick reference paths

| Need | Path |
| --- | --- |
| Procedure | `../zeus_client_design/HOW_TO_MAKE_A_CLIENT.md` |
| Autonomy stop | `../zeus_client_design/docs/autonomy/CANDIDATE_CHARTER.md` |
| Golden G0–G8 | `../zeus_client_design/docs/autonomy/CLOSED_WORLD_GOLDEN_PATH.md` |
| V2 architecture | `docs/V2/DESIGN.md` |
| V2 phases | `docs/V2/IMPLEMENTATION_GUIDE.md` |
| Security | `docs/V2/SECURITY.md` |
| ZCM catalogue | `../zeus_client_design/MICHAEL_WISHLIST.md` |
| ZCM→module map | `../zeus_client_design/docs/MICHAEL/04-wishlist-implementation-map.md` |
| OpenAPI | `../Zeus/docs/openapi.yaml` |
| BASE packs | `../Zeus/ai/zeus_chat_request/v2/base/` |
| Wire mocks | `../zeus_client_design/wire/` |
| Suite | `../zeus_client_design/conformance/` |
| 0.3.1 oracle code | `src/` + `tests/` |
