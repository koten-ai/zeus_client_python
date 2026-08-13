# Zeus Client V2 — Migration Guide

**Status:** dual-tree **beta** (`zeus_client_v2` **2.0.0b1**, claim `candidate`)  
**Default import:** still `import zeus_client` → **0.3.1** under `src/`  
**V2 import:** `import zeus_client_v2`  
**Cutover (default import = V2, PyPI 2.0.0):** **deferred** until suite required + human MATRIX + one demo BFF green — see §Cutover gate.

---

## Why dual-tree still?

Live monorepo demos (`demo_yelp`, etc.) bind `file:../zeus_client_python` and expect `import zeus_client` + `zeus_client_version` **0.3.1**. Phase 8 hardens V2 and ships **compat shims + migration notes** without breaking those BFFs in the same PR as GA tag.

| Package | Path | Version clock |
| --- | --- | --- |
| `zeus_client` | `src/` | `0.3.1` (default) |
| `zeus_client_v2` | `src_v2/zeus_client/` | `2.0.0b1` |

---

## Quick map (V1 → V2)

| V1 | V2 |
| --- | --- |
| `async with ZeusClient()` | `async with ZeusRuntime.from_config(...)` |
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

1. Keep monorepo path on **`zeus_client` 0.3.1** until cutover PR.  
2. Health chrome should keep reading `zeus_client.__version__` (0.3.1) — do **not** point at `zeus_client_v2` for product version until cutover.  
3. New V2 spike route (optional): import `zeus_client_v2`, build `ZeusRuntime`, wire `HttpxZeusPort` + LLM from existing demo config.  
4. Typeahead: map `/api/suggest` → `rt.data.search` (not `run_agent`).  
5. Reviews list: `rt.data.find` + optional N1QL hydrate outside the client when needed.  
6. Detective: prefer `result.debug.detective` over inventing Hub HTML scrapes.  
7. After cutover: swap import, run demo `pytest -q`, confirm `GET /api/health` versions.

---

## Cutover gate (when default import becomes V2)

Do **not** claim GA / flip default until **all** of:

1. Full `pytest -q` green (V1 oracle tree can move to `compat` or archive).  
2. Conformance required offline cases green (honest `candidate` → only then consider `supported` with human MATRIX).  
3. One production-shaped demo BFF migrated and smoke-tested.  
4. Security checklist in [SECURITY.md](./SECURITY.md) §23 implemented or ticketed.  
5. `project.version` / `__version__` aligned to **2.0.0**.  
6. Design-repo MATRIX row updated in a **separate** design PR (no self-award).

Until then: ship `zeus_client_v2` as **2.0.0bN candidate**.

---

## GA cutover train (ZCP-33)

**Plan:** `.hermes/plans/2026-08-13_040155-zeus-client-python-v2-ga-cutover.md`  
**Epic:** [ZCP-33](https://kotenai.atlassian.net/browse/ZCP-33) · stories ZCP-34…43 · yelp blocker [ZD-20](https://kotenai.atlassian.net/browse/ZD-20)

| Step | Key | Status entering train |
| --- | --- | --- |
| T0 gate audit | ZCP-34 | Done — branch `feat/ZCP-ga-cutover-2.0.0`, pytest 672 |
| T1 docs hygiene | ZCP-35 | this section + wishlist design PR |
| T2 prod security | ZCP-36 | production rejects `auth_mode=none` + `tls_verify=false` |
| T3 alias cleanup | ZCP-37 | drop `run_fast_suggest*`; freeze `__all__` |
| T4 demo_yelp BFF | ZCP-38 / ZD-20 | **blocker** — migrate before package-dir flip |
| T5 default import | ZCP-39 | flip + version **2.0.0** |
| T6–T9 | ZCP-40…43 | alias, docs, verify, tag + human MATRIX |

**Claim:** remains `candidate` until human MATRIX (T9). Agent must not self-award `supported`.

**Hard rule:** demo_yelp native `rt.*` **before** default-import flip (T4 before T5).

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
