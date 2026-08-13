# Zeus Client V2 — Migration Guide

**Status:** **GA cutover landed** on `feat/ZCP-ga-cutover-2.0.0` — package **2.0.0**, claim still **`candidate`** until human MATRIX  
**Default import:** `import zeus_client` → Runtime tree under `src/zeus_client/` (**2.0.0**)  
**Deprecated alias:** `import zeus_client_v2` → re-exports `zeus_client` with `DeprecationWarning` (remove ≤2.1.0)  
**V1 archive:** `src_v1_legacy/` (not installed); free functions via `zeus_client.compat.v1` only

---

## Packaging (after cutover)

| Package | Path | Version clock |
| --- | --- | --- |
| `zeus_client` | `src/zeus_client/` | **2.0.0** (default) |
| `zeus_client_v2` | `src/zeus_client_v2_alias/` | **2.0.0** (deprecated alias) |
| V1 free functions | `src_v1_legacy/` | archive only |

---

## Quick map (V1 → V2)

| V1 | V2 |
| --- | --- |
| `async with ZeusClient()` | `async with ZeusRuntime(...)` / `from_config` |
| `run_agent(url, zcfg, base_url, key, model, …)` | `await rt.agent.run_turn(msg, target=..., settings=...)` |
| `(answer, trace, turns, session_meta)` | `TurnResult` (`answer`, `debug`, `status`, `session`, …) |
| `run_search` / `run_find` | `rt.data.search` / `rt.data.find` |
| `trace["detective"]` | `result.debug.detective` |
| Mutable `trace` dict | Execution journal + projectors (`rt.debug`, public_trace) |
| `ZEUS_CLIENT_FORCE_TRACE` | `DebugPolicy` / settings `force_trace` / same env on loader |
| `ZEUS_CLIENT_DETECTIVE=0` | `DebugPolicy.detective_briefing=False` |

### Config keys

| V1 | V2 |
| --- | --- |
| `zeus.url` | `RuntimeConfig.zeus.url` |
| `zeus.auth_mode` | `RuntimeConfig.zeus.auth_mode` |
| `samples.*` | `RuntimeConfig.target` / `DataTarget` |
| `default_mode` | `RuntimeConfig.settings.mode` |
| `COUCHBASE_*` | reserved / opt-in (no implicit `:8093`) |

See also IG Appendix A.

---

## Minimal V2 agent example

```python
from zeus_client_v2 import ZeusRuntime, ClientSettings

async with ZeusRuntime.from_config("config.json", profile="development") as rt:
    # Wire ports in app bootstrap (zeus HTTP + LLM) before run_turn.
    result = await rt.agent.run_turn(
        "Find sushi in SF",
        settings=ClientSettings(ai_process_result=False),  # cheap product
    )
    print(result.answer)
    print(result.debug.detective)  # operator plane — not chat UI
```

## Minimal V2 typeahead (Direct only)

```python
from zeus_client_v2 import ZeusRuntime, SuggestOptions

async with ZeusRuntime.from_config() as rt:
    # rt.services.zeus must be an HttpxZeusPort (or fake) bound by the app
    sug = await rt.data.search("sushi", options=SuggestOptions(limit=8))
    payload = sug.to_dict()  # BFF JSON
```

**Never** call the agent plane per keystroke.

## Direct verbs

```python
r = await rt.data.find({"entity_type": "Review", "where": {"business_id": bid}, "limit": 20})
# r.ok, r.body, r.req_id
```

`pipeline` is **not** on the public Direct surface (`ErrorCode.ZEUS_PIPELINE_NOT_ON_DIRECT`).

---

## Compat shims (deprecated)

```python
from zeus_client_v2.compat.v1 import run_agent, run_search, run_verb, turn_result_as_v1_tuple

# Requires an already-wired ZeusRuntime — no process-global HTTP recreation.
result = await run_agent("hello", runtime=rt)           # DeprecationWarning
answer, trace, rounds, meta = await run_agent(
    "hello", runtime=rt, legacy_tuple=True
)
hits = await run_search("sushi", runtime=rt)
vr = await run_verb("find", {"entity_type": "Business", "limit": 5}, runtime=rt)
```

Shims are **time-boxed ≤1 minor** after default-import cutover. New code must use `rt.*`.

---

## Rate limits & metrics (Phase 8)

| Control | Default | Config |
| --- | --- | --- |
| Typeahead token bucket | 10 rps, burst 20 | `RuntimeConfig.rate_limit` / JSON `rate_limit` |
| Metrics | in-process `InMemoryMetrics` | `rt.metrics.snapshot()` |

Exceeded typeahead limit → `ZeusClientError(ErrorCode.CLIENT_RATE_LIMITED)` and counter `zeus_client_rate_limited_total{surface=typeahead}`.

Recommended counter names (BEST_PRACTICES §5.2):

- `zeus_client_turns_total{status,mode}`
- `zeus_client_zeus_hops_total{verb,status_class}`
- `zeus_client_errors_total{code}`
- `zeus_client_rate_limited_total{surface}`
- `zeus_client_typeahead_total{source}`

Optional OTLP: `zeus_client_v2.adapters.otlp.try_build_otlp_exporter` — no-op unless explicitly enabled; no hard OpenTelemetry dependency.

---

## demo_yelp / BFF notes

1. **demo_yelp** migrated (ZD-20 `844f61b`) — native `rt.*`; health may report alias or default import version **2.0.0**.  
2. Prefer `import zeus_client` going forward; `zeus_client_v2` still works with DeprecationWarning.  
3. Typeahead: `/api/suggest` → `rt.data.search`.  
4. Reviews / detail: `rt.data.find` + app-side N1QL hydrate when needed.  
5. Detective: prefer `result.debug.detective`.  
6. After package upgrade: reinstall editable client, `pytest -q`, confirm health `zeus_client_version`.

---

## Cutover gate

| # | Gate | Status |
| --- | --- | --- |
| 1 | Full `pytest -q` green | **Met** — package **238** (V1 oracles → `tests/legacy_v1`) |
| 2 | Conformance offline required | **Met** (candidate) |
| 3 | Production-shaped demo BFF | **Met** — Travel ZD-8, sample ZC-56, yelp ZD-20 |
| 4 | SECURITY §23 | **Met** — prod rejects auth_mode=none + tls_verify off; pip audit = ZCP-44 |
| 5 | Versions **2.0.0** | **Met** — `c123f52` |
| 6 | Design MATRIX `supported` | **Open** — human only (T9) |

Ship **2.0.0** with claim **candidate** until human MATRIX PR.

---

## GA cutover train (ZCP-33)

**Plan:** `.hermes/plans/2026-08-13_040155-zeus-client-python-v2-ga-cutover.md`  
**Epic:** [ZCP-33](https://kotenai.atlassian.net/browse/ZCP-33) · stories ZCP-34…43 · yelp [ZD-20](https://kotenai.atlassian.net/browse/ZD-20)

| Step | Key | Status |
| --- | --- | --- |
| T0 gate audit | ZCP-34 | **Done** |
| T1 docs hygiene | ZCP-35 | **Done** |
| T2 prod security | ZCP-36 | **Done** `4c73ed9` |
| T3 alias cleanup | ZCP-37 | **Done** `546e280` |
| T4 demo_yelp BFF | ZCP-38 / ZD-20 | **Done** yelp `844f61b` · 78 pytest |
| T5 default import | ZCP-39 | **Done** `c123f52` · 2.0.0 |
| T6 v2 alias | ZCP-40 | **Done** meta-path submodule redirect |
| T7 docs | ZCP-41 | **Done** `9eb9ff6` |
| T8 verify | ZCP-42 | package 238 · yelp 78 · sample 245 |
| T9 tag + MATRIX | ZCP-43 | **Human** — do not self-award |

**Claim:** remains `candidate` until human MATRIX (T9).

---

## Security review snapshot (ZCP-22)

| Control | Status |
| --- | --- |
| SecretStorePort + env names only in config | **done** |
| Redactor on journal / exports | **done** |
| Typeahead rate limiter | **done** (this phase) |
| Metrics `rate_limited` | **done** |
| Tool POST retries default off | **done** (adapter law) |
| Hub hydrate opt-in | **done** |
| LIVE replay gated | **done** |
| Prod rejects `auth_mode=none` | **done** (ZCP-36 — production profile + `tls_verify`) |
| `pip audit` in CI | **deferred** (ops) |
| Plugins deny-by-default secrets | N/A (plugins=no) |
| OTLP optional | **stub** (opt-in factory) |

---

## Breaking changes to plan for

- No tuple public returns on V2 native API.  
- No process-global HTTP client on V2 paths.  
- No public `run_pipeline` / `rt.data.pipeline`.  
- Catalog resolve never silent sibling `*__*` rglob.  
- Package `ai_process_result` default remains **True** (Hub); pins may document product-cheap **false**.  
- G2 / scores / `wish_i_knew` never in user-facing `answer`.
