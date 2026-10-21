# Changelog

## Unreleased

### Fixed

- `gpt-5.6` no longer receives `temperature` on the chat-completions body. Every turn was sending `temperature: 0`, and `gpt-5.6` answered with HTTP 400 (`050017`, `llm invalid request`). Omitting the field uses the provider default of 1. The same ids (`gpt-5.6-sol` and a provider prefix) send `max_completion_tokens` instead of `max_tokens` when a cap is set. Other models still send `temperature: 0` and `max_tokens`. (ZCP-129)
- OpenAI Chat Completions accepts stock catalog tools. `build_chat_payload` fills schema nodes that have no `type` (description-only `narrow_to`, empty array `items`, nested `set` inputs) on a copy of the tools. `strict` stays unset, so `additionalProperties: true` and boolean maps still send. xAI keeps accepting the same payload. (ZCP-127)

---

## 2.5.1 — 2026-10-15

### Fixed

- Session trace passes the turn target into `post_trace`. A beer-sample basic-auth turn mints `/v1/{bucket}/{scope}/auth/session` for that target. `DataTarget()` is no longer the trace login when the turn named a bucket. (ZDM-16)
- Session create, turn, and trace JSON include `bucket` and `scope` only when a target is passed and both sides are non-empty. A missing target leaves those fields off the body. (ZCP-120)

### Changed

- `auth_mode=pat` and `auth_mode=m2m` stay in the config vocabulary but are disabled until ZE-360 and ZE-361. The loader and auth resolver raise `FEATURE_DISABLED` (`000008`) and do not read a token or client secret (ZCP-126).
- The available Zeus 1.0.0 client package is `kotenai-zeus-client` tag `v2.5.1`. `v2.4.1` is the previous tag. Auth on `v2.5.1` is `basic`, `bearer`, and `session`. PAT and M2M stay disabled (ZCP-124).
- Record ZCP-44: `pip-audit` stays non-blocking for 2.0.0 and does not block T5/T8/T9. The failing CI job is 2.0.1.

### Added

- `auth_mode=pat` mints a Zeus session from a `zeus_pat_…` token (`ZEUS_PAT` or `token_env`), then sends `X-Zeus-Session`. Tokens that do not start with `zeus_pat_` are not sent (ZCP-123). The mode is disabled until ZE-360.
- `auth_mode=m2m` fetches an IdP JWT with client credentials and mints a Zeus session. The client secret stays in `ZEUS_M2M_CLIENT_SECRET` (ZCP-122). The mode is disabled until ZE-361.

---

## 2.4.1 — 2026-09-15

### Added

- Zeus HTTP `RetryBudget` on idempotent read verbs (`find`/`get`/`search`/`describe`/`explain`/`traverse`) for transport + HTTP 5xx only (API_ZEUS §6.6). Never 4xx/409/429, never `set`/`pipeline`. Same budget as LLM adapters. Claim stays **candidate**. Not V1 job replan.

### Changed

- Relicense package to **BSD-3-Clause** (ZCP-119).

### Security

- Remove Zeus engine catalogs from the tree; scrub docs and restore a redacted legacy `chat_requests` README after history purge.

---

## 2.4.0 — 2026-09-04

### Pins (ZCF-WISH-030)

```text
suite_version: conformance-0.2-dev
client_floor: client-floor-5
claim_level: candidate
semantic_cache: flag (CHECKLIST E2 / ZF-WISH-001; default enabled=false)
BASE packs tested: offline mock base-5-mock; pack fixtures base-5.3; pin-shaped base-1 (not a COMPAT triple)
zeus_engine: 0.6.x offline tapes; live agent_memory requires a Zeus build that exposes it
zeus_client_design: 4ba1df97fcc56b9f1627561a8d1047195980b5ee
compat_row: none — do not invent; see chat_request COMPAT.md
multi_agent: docs
hub_join: v1 (ZCP-113 client half)
```

### Added (hub-join-v1 · ZCP-113)

- Hub-shaped `zeus_response.inject` on `POST /v2/session/trace` and `public_trace.inject`: nested `scope_brief` / `mini_schema` with `present`, UTF-8 `chars`, slice `sha12`, `preview`, `entity_types` / `scope_line` / `mode_line`. `rewind=true` adds capped `text` (96 KiB). Entity types parse from `###` headings in the mini slice, not `catalog.mini_entity_types`. Direct verb JSON still does not carry `## MINI-SCHEMA`. (ZCP-114)
- Aggregate `zeus_response.tokens` (`prompt` / `completion` / `total` / `rounds` / `ok`, optional `cached`) from `sum_provider_tokens`. Omitted when the turn never called the LLM or usage is unknown. (ZCP-115)
- Stamp `turn_id` on `POST /v2/session/trace`. Agent/Direct/session hops send `X-Zeus-Chat-Session-Id` (durable chat session, not auth `X-Zeus-Session`) plus `X-Zeus-Brief-Sha12` / `X-Zeus-Mini-Sha12` matching the inject-bag slice hashes. Never sets `X-Zeus-Req-Id`. (ZCP-116)
- `zeus_response.catalog` (tool_count / tool_names / has_return_verb / has_pipeline_verb), compact `layer_a` when a terminate bag parsed, and `terminate` flags. G2 fields stay off `layer_a`. (ZCP-117)

### Added

- Opt-in Zeus verbose persist: `DebugPolicy.rewind` / `ZEUS_REWIND=true` sends query `rewind=true` on V2 verbs and query+body on session create/turn/trace. Default **off**. `X-Zeus-Trace: 1` still only force-keeps; it does not upgrade slim → verbose. Verb JSON never forwards a `rewind` argument. (ZCP-112)
- Recover HTML pipeline envelopes as tool calls.

### Security

- Floor-5 jailbreak control plane: multi-surface scorer (`zeus_client.security.jailbreak`) covering catalog families R–H (paraphrase dump, clean terminate, commercial invent, retrieval injection, multi-turn grooming, encoding, summary leak).
- `SecurityHooks` scores those surfaces, allowlists catalog verbs, and replaces poisoned Zeus bodies with `untrusted_tool_payload`. Hard refuse (`>= 0.85`) skips the LLM/Zeus loop. (ZCP-101)

---

## 2.3.0 — 2026-08-20

### Pins (ZCF-WISH-030)

```text
suite_version: conformance-0.2-dev
client_floor: client-floor-5
claim_level: candidate
semantic_cache: flag (CHECKLIST E2 / ZF-WISH-001; default enabled=false)
BASE packs tested: offline mock base-5-mock; pack fixtures base-5.3; pin-shaped base-1 (not a COMPAT triple)
zeus_engine: 0.6.x offline tapes; live agent_memory requires a Zeus build that exposes it
zeus_client_design: 4ba1df97fcc56b9f1627561a8d1047195980b5ee
compat_row: none — do not invent; see chat_request COMPAT.md
multi_agent: docs
```

### Added

- CHECKLIST **E2** semantic agent cache (ZF-WISH-001): L0 `session.semantic_cache` (default **`enabled=false`**), bag B inject key `semantic_memory`, fail-open recall timeout, explicit `rt.session.semantic_cache.write` / `.recall` / `.status`.
- HTTP adapter `POST /v2/agent_memory/recall|blocks` + `GET /status` (Zeus embeds server-side; no client CB vector SDK).
- Client deny-list: secrets, full system/catalog dumps, G2 fields are not written.
- Direct typeahead / data verbs never call agent_memory (`apply_to_modes=["agent"]`).
- CHECKLIST **F** closeout at `multi_agent=docs`: per-unit `zeus_url` + auth env names on every Zeus hop this process executes; worker `llm.roles` slice (including `api_key_env` / `base_url`) applied to `units.agent_turn`; job `models` forwarded through FakeJobRuntime; optional `UnitResult.artifacts["usage"]`.
- Package docs: EXAMPLE §0 runbook map, JobEvent/budget/cost ownership in `docs/V2/MULTI_AGENT.md`. `config.example.json` includes `llm.roles` and `jobs.host_url` (placeholders; env **names** only).

### Not claimed

- MATRIX `semantic_cache=supported` (Zeus recall MVP; no shared suite cases yet). Honest value is **`flag`**.
- Family `supported` / new COMPAT triple / `multi_agent=demo`.

---

## 2.2.0 — 2026-08-20

### Pins (ZCF-WISH-030)

```text
suite_version: conformance-0.2-dev
client_floor: client-floor-5
claim_level: candidate
BASE packs tested: offline mock base-5-mock; pack fixtures base-5.3; pin-shaped base-1 (not a COMPAT triple)
zeus_engine: 0.6.x (Detective tapes sample 0.6.64; pins.live_smoke=false)
zeus_client_design: 4ba1df97fcc56b9f1627561a8d1047195980b5ee
compat_row: none — do not invent; see chat_request COMPAT.md
multi_agent: docs
detective_tapes: smooth_short + fail_zeus (+ fail_client / fail_llm / fail_control_plane / smooth_long)
```

### Breaking

- `ClientSettings.ai_process_result` default is **`false`** (CHECKLIST / API_CONFIG). Use profile **`hub`** (or set the flag) for Hub Debug insight.
- Array `business_rules_triggers` dual-read **removed** on V2. Object `{id: bool}` only. Arrays fail closed.
- `auth_mode=basic` now **mints a per-scope session** (`POST /v1/{bucket}/{scope}/auth/session`) instead of sending HTTP Basic on every hop.

### Added

- CHECKLIST D (sessions / observability / stamps): product sink `user=zeus_client` + optional `ip_address`; family logger (`INFO`/`ERROR`/`DEBUG`/`TRACE`, `REDACT`); UUID v4 chat/turn/call mint; full `X-Zeus-Req-Id` capture on 4xx/5xx; optional OTLP Logs extra `[otel]`; auto-wired durable `SessionLifecycle`.
- `rt.catalog.load(..., base_id=)` / `info` / `load_pin` / `contract.hash|id|bind` / `mini_schema.get|from_catalog` (CHECKLIST A).
- Same-`base_id` `response_output_schema.json` + `response_output_example.json` load; fail-closed when pack wire > `client_floor`.
- Offline pin-shaped `base-1` fixture (not a COMPAT triple).
- Named `rules{}` merge/freeze (`domain.rules`) wired into `run_agent_turn` inject.
- Soft `session.ignore_user_tool_path_hints` inject (default **true**).
- Force-return nudge near `max_rounds`; `TurnResult.tool_trail` + bag B inject.
- Baseline `SecurityHooks` (prompt-dump / secrets / denied verbs) and dual jailbreak scores on policy.
- Turn journal + `debug.catalog` carry `base_id` and `client_floor`.
- Profile **`hub`** (`ai_process_result=True`).
- Documented-but-deferred `auth_mode=certificate` (`cert_file` / `key_file_env`).
- Agent `run_turn` / `catalog.load_for_turn` borrow live `## SCOPE BRIEF` + `## MINI-SCHEMA` when the on-disk catalog has none (V1 `merge_scope_brief`).
- Cheap-final no longer treats `describe` / `explain` as product data (orientation hops keep looping).
- CHECKLIST E: conformance adapter drives V2 APIs for fail tapes (no lang-only expect-echo); CI requires sibling design suite; GitHub README links CHECKLIST / MATRIX / COMPAT.

### Not claimed

- MATRIX `supported` / new COMPAT triple / `multi_agent=demo`.
- Full Detective agent rewind (ZF-WISH-003). Kit-β companions + slim assert_only only.

---

## 2.1.0 — 2026-08-18

### Added

- Optional Mode 3 seam: `rt.jobs.*` + `rt.units.agent_turn` / `zeus_direct` + `config.llm.roles` (ZCP-64…75).
- Family error band `130001`–`130013` (`JobError`).
- Pattern B HTTP/SSE **WatchJob** client (`GET /v1/jobs/{id}/events?from_seq=`). `run`/`get`/`cancel` stay `130001` until the Go sidecar grows those routes.
- Test-only `FakeJobRuntime` (not a product engine; not a MATRIX `demo`).
- Package docs: `docs/V2/MULTI_AGENT.md`.

### Changed

- Claim `multi_agent` → **`docs`**. `claim_level` remains **candidate**.
- `zeus_client_v2` alias kept; removal slipped to **≤2.2.0** (yelp still imports `_v2`).
- `DataAPI.verb` accepts optional per-call `target=` and Rewind `chat_id` / `turn_id`.

### Not claimed

- `multi_agent=demo` / `supported`
- Native Python orchestrator / FFI / `http_json` units / WS / gRPC

---

## 2.0.0 — 2026-08-13

### Breaking

- **Default import is the journaled hexagonal Runtime tree.**  
  `import zeus_client` → `ZeusRuntime`, typed `TurnResult` / `VerbResult` / `SuggestResult`.  
  Free-function API is **not** the default; use `zeus_client.compat.v1` (deprecated, ≤1 minor) only as a migration aid.
- **No tuple public returns** on the native API (`run_agent` style 4/5-tuples).
- **No process-global HTTP/auth** on V2 paths (`init_http` / shared client removed from default path).
- **No public `run_pipeline` / `rt.data.pipeline`** (pipeline remains agent-internal only).
- **Catalog resolve** never silent-sibling `*__*` rglob across scopes.
- **`run_fast_suggest*` removed** — use `run_search` / `rt.data.search` (ZCM-032).
- **Production profile** rejects `auth_mode=none` and `tls_verify=false` (SECURITY §23).

### Added

- Temporary **`zeus_client_v2` deprecation alias** (warn + submodule redirect) through ≤2.1.0 for BFFs that already import `_v2`.
- `ZeusEndpointConfig.tls_verify` (default `True`).
- Public export freeze tests; GA cutover train docs (ZCP-33…43).

### Changed

- Package / `__version__` clocks aligned to **2.0.0**.
- V1 free-function tree archived under `src_v1_legacy/` (not installed).
- `sdk_bootstrap.pins.json` `last_reviewed`; **`claim_level` remains `candidate`** until human MATRIX.

### Migration

See `docs/V2/MIGRATION.md`. Dogfood BFFs: Travel ZD-8, sample ZC-56, demo_yelp ZD-20.

---

## 0.3.1 and earlier

See git history / prior release notes on dual-tree beta (`zeus_client_v2` 2.0.0b1).
