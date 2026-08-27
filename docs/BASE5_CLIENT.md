# base-5 Client control plane (V2 Runtime)

**Status:** V2 `ZeusRuntime` implements CHECKLIST A/B/C/D at **`candidate`**.  
**SoT packs:** [zeus_chat_request](https://github.com/koten-ai/zeus_chat_request) `v2/base/base-5.3/` (wire = base-5).  
**Pin:** production `CURRENT.json` remains **base-1** — do not invent stamps; Hub stamp only.

V1 names (`run_agent`, `load_base_catalog`) are **not** the default package surface. Use `ZeusRuntime` / `rt.catalog` / `rt.agent.run_turn`. Migration aid: `zeus_client.compat.v1`.

## What the Runtime exposes

| Capability | API |
| --- | --- |
| Load by `base_id` | `await rt.catalog.load(mode, base_id="base-5.3")` |
| Catalog list / info | `rt.catalog.list()` · `rt.catalog.info(mode, base_id=...)` |
| Stamp extract / bind | `rt.catalog.contract.hash(doc)` · `.id(doc)` · `.bind(bucket, scope, mode, doc)` — **never invent** |
| Mini-schema | `rt.catalog.mini_schema.from_catalog(doc)` · `await rt.catalog.mini_schema.get(...)` |
| Live SCOPE BRIEF | `await rt.catalog.load_for_turn(...)` / `ensure_scope_brief` (automatic on `run_turn`) |
| Pack schema | Sibling `response_output_schema.json` on `LoadedCatalog.response_output_schema` |
| Settings bag + rules merge/freeze | `ClientSettings.rules` / `tenant_rules` · `prepare_settings` · `merge_rules` |
| Default jailbreak named rules | always merged unless `override_defaults=True` |
| Prompt inject (hash-excluded) | company_context, rules{}, output_request, session meta, TOOL PATH POLICY |
| Layer A parse | `parse_layer_a` — required four + object triggers + `app_output` |
| Array triggers | **removed** — object `{id: bool}` only |
| Policy table | every terminate → `policy`, `ui`, `artifacts` |
| Dual jailbreak scores | model `jail_break_attempt` **and** `hooks_jailbreak_score` (never same field) |
| G1 UI vs artifacts | `structured.ui` vs `structured.artifacts` (G2 never chat UI) |
| AI on Zeus result | `ClientSettings.ai_process_result` default **`false`**. Profile **`hub`** binds `True`. |
| Tool trail | `TurnResult.tool_trail` + bag B inject (default on) |
| Force return | `force_return_rounds_left` (default 1) |

## Minimal example

```python
from zeus_client import ZeusRuntime, ClientSettings

async with ZeusRuntime.from_config("config.json", profile="production") as rt:
    settings = ClientSettings(
        company_context="We are a craft beer guide.",
        rules={"loyalty": "Apply loyalty only from tool data."},
        output_request={
            "app": {
                "fields": {
                    "offer_code": {
                        "type": "string",
                        "description": "Promo code if user presented one, else empty",
                    }
                }
            }
        },
        locale="en-US",
        channel="web",
        ai_process_result=False,  # cheap product path
    )
    result = await rt.agent.run_turn(
        "Fruity beers under 6% ABV",
        settings=settings,
        base_id="base-5.3",
    )
    print(result.answer)                 # G1 only
    print(result.structured.policy)
    print(result.tool_trail)             # not chat chrome
    print(result.debug.req_ids)
```

## `ai_process_result` (ZC-WISH-044)

| Value | Loop after Zeus tool data |
| --- | --- |
| **`false` (package / development / production / ci)** | Cheap path — no second LLM hop. |
| **`true` (profile `hub` or explicit setting)** | Insight path — one no-tools synthesis turn after terminate. |

When insight is on and `max_rounds < 2`, Client raises the floor to 2.

## Hash safety

Injects splice **after** `## SCOPE BRIEF` / `## MINI-SCHEMA` only.  
`compute_contract_hash` before/after inject must match when the brief marker is present.

## Floor vs pack wire

`RuntimeConfig.client_floor` (default `client-floor-5`) is independent of package semver. Loading `base-6.1` on a floor-5 client **fails closed** unless `allow_degraded_catalog=True`.

## Compatibility

- Legacy `*_v2.json` load path unchanged when `base_id` is omitted.
- Prefer named `settings.rules` for new base-5 work.
- base-6 soft `hints.*` inject is **not** in this train.
- Claim remains **`candidate`**. Do not treat this doc as MATRIX `supported`.

## CHECKLIST A / B / C (Python V2 · candidate)

Ticked only when the V2 Runtime implements the item **and** a unit (or offline suite) test locks it.  
Family [CHECKLIST.md](../../zeus_client_design/CHECKLIST.md) §A–C records these as **Python V2 candidate** ticks only — not Go/Hub, not MATRIX `supported`.

### A. Contract / catalog / schema versioning

- [x] Load stamped `chat_request` by `base_id` / `cus-*` / `_lineage` — `tests/unit/domain/test_catalog_lineage.py`
- [x] `catalog.list` / `catalog.info` (mode, lineage, stamp present, verb count) — `test_catalog_lineage.py`, `tests/unit/api/test_catalog.py`
- [x] `catalog.contract.hash` / `.id` / `.bind` (stamp only; never invent) — `test_catalog.py`
- [x] Support production pin path per chat_request COMPAT (offline `base-1` pin-shaped fixture; not a COMPAT triple) — `test_pin_path_load_and_bind`
- [x] Primary schema = pack `response_output_schema.json` — `test_catalog.py` (`has_response_schema`)
- [x] Load catalog + schema + **example** for the same `base_id` — `test_load_info_and_pack_schema`
- [x] Validate terminate required four + types; G2 never UI — `tests/unit/domain/test_layer_a.py`, `test_g2_stays_out_of_answer_on_bad_layer_a`
- [x] Track envelope / `base_id` / `client_floor` separately from package semver — `test_catalog.py`, `tests/unit/domain/test_floor.py`
- [x] Declare supported BASE packs + floor in MATRIX — design `MATRIX.md` candidate row (not `supported`)
- [x] Fail closed when pack wire > `client_floor` (or `allow_degraded_catalog`) — `test_floor.py`, `test_catalog.py`
- [x] Dual-read migrations removed — arrays rejected; `test_array_triggers_rejected_by_default`
- [x] Do not invent or forge `contract_hash` — `test_contract_bind_never_invents`
- [x] Scope brief / mini-schema inject hash-excluded — `tests/unit/application/test_control_plane_inject.py`
- [x] Live SCOPE BRIEF borrow on agent path — `tests/unit/application/test_catalog_brief.py`, `tests/unit/api/test_catalog.py`
- [x] `catalog.mini_schema.get` / `from_catalog` — `tests/unit/domain/test_mini_schema.py`, `test_catalog.py` (live remote hop not mocked)
- [x] Catalog sync from Zeus — `tests/unit/application/test_catalog_sync.py`
- [x] Log `base_id` + `client.floor` on catalog load / turns — `test_turn_logs_base_id_and_client_floor`

### B. Agent loop

- [x] Auth stubs: `none` / per-scope `basic` mint / `bearer` / `session`; `certificate` documented + `NOT_IMPLEMENTED` — `tests/unit/adapters/test_zeus_auth.py`
- [x] Never log bearer tokens or passwords — `test_zeus_auth.py`
- [x] Multi-round LLM → Zeus V2 verbs → append results — `tests/unit/application/test_agent_turn.py`
- [x] Bags A–D append `messages[]` (user text unchanged) — `test_control_plane_and_tool_path_inject_into_system`
- [x] Client clock on round; mode switch = new session — `test_mode_switch_creates_new_session`, session-lifecycle round tests
- [x] Force final return when budget / `max_rounds` low (logged) — `test_force_return_nudge_before_last_rounds`
- [x] Setting `ai_process_result` default **false** — `test_ai_process_result_package_default_false`; profile `hub` is True
- [x] `ignore_user_tool_path_hints` default **true**; soft inject; user message unchanged — `test_control_plane_and_tool_path_inject_into_system`, `test_tool_path_honor_polarity_keeps_user_text`
- [x] Durable sessions `/v2/session*` rehydrate id + round — `tests/unit/application/test_session_lifecycle.py`, `test_agent_turn_session_join.py`
- [x] `agent.tool_trail`: record, inject, expose on result — `test_tool_trail_injects_after_409`
- [x] Trail entries `ok` + `error_class` + `req_id`; no secret dumps — same test

### C. Control plane (floor-5)

- [x] Inject named `rules{}` — `test_control_plane_inject.py`, `test_agent_turn.py`
- [x] Rule pack merge + freeze (SDK ∪ tenant ∪ request; append-only; `ruleset_id`) — `tests/unit/domain/test_rules.py`, suite `L2.rules.merge_freeze`
- [x] Parse object `business_rules_triggers` (missing ⇒ false) — `test_layer_a.py`
- [x] Dual-read sunset then **remove** — arrays rejected (`test_array_triggers_rejected_by_default`)
- [x] `company_context` inject + 150/250 word budget — `test_company_context_hard_truncate`, inject tests
- [x] Structured settings bag — `test_prepare_settings_merges`
- [x] `output_request` fields require type + description — `test_prepare_rejects_type_only_output_field`
- [x] Validate `app_output` on terminate (strip/fail) — `test_layer_a.py`
- [x] Post-terminate policy table on every `return` — `tests/unit/domain/test_policy.py`, `test_single_tool_then_return_insight`
- [x] Required four always validated — `test_layer_a.py`, `test_g2_stays_out_of_answer_on_bad_layer_a`
- [x] G1/G2/G3: G2 never chat UI; raw Layer A in artifacts — `test_ui_view_strips_g2`, turn G2 test
- [x] AgentHooks baseline (prompt-dump / secrets / denied verbs) — `test_hooks_refuse_prompt_dump`, `test_denied_verb_skips_zeus_and_scores`
- [x] Jailbreak attempt catalog (ZCP-101): multi-surface score, pre-LLM refuse, tool-JSON sanitize, summary leak, request-rule lock — `tests/unit/security/test_jailbreak.py`, `tests/unit/application/test_jailbreak_turns.py`
- [x] Dual jailbreak scores; do not overwrite `jail_break_attempt` — `test_policy.py`, `test_hooks_refuse_prompt_dump`

### E. Conformance & release (Python V2 · candidate · 2.3.0)

- [x] Semver bumped; CHANGELOG filled — package **2.3.0**
- [x] Notes include floor id, suite version, Zeus versions tested, BASE packs tested — CHANGELOG `## 2.3.0` pin block
- [x] Conformance suite green for claimed floor — `tests/conformance/test_conformance_suite.py` (`conformance-0.2-dev` L0–L2 + DT)
- [x] Detective tapes: `smooth_short` + fail families — same suite (`DT.smooth_short.*`, `DT.fail_zeus.*`, …)
- [x] Same `error_class` as shared tapes (no lang-only expect-echo) — `test_handlers_do_not_echo_expect`; fail handlers drive V2 APIs
- [x] Language README links CHECKLIST + MATRIX + chat_request COMPAT (GitHub URLs)
- [x] Dual-read sunset — arrays rejected (`test_array_triggers_rejected_by_default`)
- [x] MATRIX.md row in design repo — Python candidate honesty (same train; `semantic_cache=flag`)

Claim remains **`candidate`**. Do not treat this section as MATRIX `supported`.

### E2. Semantic agent cache (ZF-WISH-001)

- [x] L0 `session.semantic_cache` (default **`enabled=false`**)
- [x] Zero `/v2/agent_memory` traffic when off
- [x] Recall → bag B `semantic_memory` inject; fail-open timeout
- [x] Explicit write (`rt.session.semantic_cache.write`); Zeus embeds; no CB SDK
- [x] Not Direct typeahead (`apply_to_modes=["agent"]`)
- [x] MATRIX honesty **`flag`** (not `supported` — [redacted-recall-impl] / no suite cases)
- [x] Deny-list: secrets, full system/catalog dumps, G2 fields are not written

### F. Multi-agent readiness (`docs` only)

- [x] Seam: Mode 1 `rt.agent.run_turn` vs Mode 3 `rt.jobs.*` / `rt.units.*` — [MULTI_AGENT.md](V2/MULTI_AGENT.md)
- [x] Pattern B attach: `jobs.host_url` → WatchJob SSE `GET /v1/jobs/{id}/events?from_seq=`; do not vendor Go; `run`/`get`/`cancel` stay `130001` until sidecar grows routes
- [x] Events / budgets / cost: JobEvent wire map, `JobBudgets`, sidecar ledger; client `llm.role` + `model` + `api_key_env` name + optional `artifacts.usage`
- [x] `config.llm.roles.orchestrator|advisor|worker` settable; worker slice applied (`llm_for_slice`); Mode 1 ignores roles; secrets are env **names**
- [x] EXAMPLE §0 runbook: per-unit `zeus_url` + auth names on hops; catalog/`130011`/`130012`; job `models` via FakeJobRuntime
- [x] MATRIX `multi_agent=docs` (not `demo` / `supported`; FakeJobRuntime is not a MATRIX demo)

## Tests

```bash
pytest tests/unit/domain/test_catalog_lineage.py \
       tests/unit/domain/test_mini_schema.py \
       tests/unit/domain/test_rules.py \
       tests/unit/domain/test_floor.py \
       tests/unit/application/test_control_plane_inject.py \
       tests/unit/application/test_agent_turn.py \
       tests/unit/adapters/test_zeus_auth.py \
       tests/conformance/test_conformance_suite.py -q
```
