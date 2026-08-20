# Changelog

## 2.2.0 — 2026-08-20

### Added

- CHECKLIST **F** closeout at `multi_agent=docs`: per-unit `zeus_url` + auth env names on every Zeus hop this process executes; worker `llm.roles` slice (including `api_key_env` / `base_url`) applied to `units.agent_turn`; job `models` forwarded through FakeJobRuntime; optional `UnitResult.artifacts["usage"]`.
- Package docs: EXAMPLE §0 runbook map, JobEvent/budget/cost ownership in `docs/V2/MULTI_AGENT.md`. `config.example.json` now includes `llm.roles` and `jobs.host_url` (placeholders; env **names** only).

### Changed

- `zeus_client_v2` alias kept; removal slipped to **≤2.3.0**.

### Not claimed

- `multi_agent=demo` / `supported`
- Sidecar `POST /v1/jobs` (still `130001` until Go grows the route)
- Native Python orchestrator / FFI / `http_json` units / WS / gRPC

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
