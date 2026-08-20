# Multi-agent Pattern B seam (package)

**Claim this release:** `multi_agent = docs`  
**Not claimed:** `demo` (needs a live `koten_multi_agent_golang` job, not fakes) · `supported` (human MATRIX only)

This package does **not** embed the job engine. Mode 1 (`rt.agent`) and Mode 2 (`rt.data`) stay the only Zeus tool planes. Mode 3 is optional: `rt.units.*` wraps those planes with isolation; `rt.jobs.*` is a port. Production adapter is HTTP/SSE to a sidecar (Pattern B). Do not vendor Go into the Python wheel.

Family SoT: `zeus_client_design/docs/multi_agent/*` · `guides/api/API_JOBS.md` · `API_UNITS.md` · `API_CONFIG.md` §7.6 · setup runbook [MULTI_AGENT_EXAMPLE.md §0](https://github.com/koten-ai/zeus_client_design/blob/main/docs/multi_agent/MULTI_AGENT_EXAMPLE.md#0-multi-agent-setup-checklist-runbook) · fruit-beer example in the same file.

---

## One turn vs one job

```text
Mode 1  rt.agent.run_turn(message)     → one chat, one worker LLM, one scope
Mode 3  rt.jobs.run(goal, units=[…])   → many isolated units; sidecar owns waves
        rt.units.agent_turn(unit)      → one Mode 1 turn (worker LLM)
        rt.units.zeus_direct(unit)     → one Mode 2 verb (no LLM, no catalog)
```

Everyday one-scope Q&A stays `rt.agent.run_turn`. Never auto-promote chat into `jobs.run`.

---

## Attach a sidecar

```json
{
  "jobs": { "host_url": "http://127.0.0.1:7090", "watch_transport": "sse" },
  "llm": {
    "model": "fast-worker",
    "api_key_env": "LLM_DEFAULT_KEY",
    "roles": {
      "orchestrator": { "model": "strong-planner", "api_key_env": "LLM_ORCH_KEY" },
      "advisor": { "model": "strong-planner", "api_key_env": "LLM_ADV_KEY" },
      "worker": { "model": "fast-worker", "api_key_env": "LLM_WORKER_KEY" }
    }
  }
}
```

`ZeusRuntime.from_config` builds `HttpxJobRuntime` only when `jobs.host_url` is set. Otherwise `rt.jobs.*` raises **`130001`**.

Current Go sidecar HTTP (do not invent the rest; if clone paths change, patch `adapters/jobs_http/paths.py` only):

```text
GET {host}/v1/jobs/{job_id}/events?from_seq=N    # WatchJob SSE
POST /v1/jobs , GET /v1/jobs/{id} , cancel       # NOT on sampledesk — 130001
```

Query param is **`from_seq`**. Also honor `Last-Event-ID`. SSE is not durable SoT.

---

## Events

Go `JobEvent` wire (do not fork names): `schema`, `seq`, `job_id`, `ts` (RFC3339), `type`, `plan_epoch`, `unit_id`, `status`, `stage`, `pct`, `summary`, `trace_id`, `duration_ms`, `dead_end`, `extra`.

Python `JobEvent` mapping:

| Wire | Python |
| --- | --- |
| `ts` | `ts_ms` (epoch ms) |
| `extra` + remaining fields | `payload` |
| `seq` / `type` / `job_id` / `unit_id` / `plan_epoch` | same |

Resume: `watch(job_id, after_seq=N)` sends `from_seq=N` and `Last-Event-ID`. Events are minified. **Never** put API keys, passwords, or full prompts on JobEvents, Detective, or support packs.

Journal (this process): `job.started` / `job.finished` / `unit.started` / `unit.finished` with `job_id`, `unit_id`, `llm.role`, `llm.model`, `api_key_env` **name**.

---

## Budgets

`JobBudgets` (invalid → **`130003`**):

| Field | Default | Notes |
| --- | --- | --- |
| `max_workers` | 4 | Sidecar enforces parallelism |
| `wall_ms` | 120000 | Sidecar wall |
| `max_waves` | 4 | Sidecar |
| `max_replans` | 2 | Sidecar |
| `max_evidence_keys` | 32 | Sidecar |
| `disable_early_cancel` | false | Sidecar |

`FakeJobRuntime` is sequential and does **not** simulate wall timeout. It is an L4 seed, not a product engine.

---

## Cost

The **cost ledger lives in the sidecar** (tokens / wall / OTel per unit and LLM role). This SDK does not reimplement it.

Client half (ZCF-043):

- Log / journal **`llm.role` + `llm.model` + `api_key_env` name** on unit start.
- When the worker LLM returns usage, copy it to `UnitResult.artifacts["usage"]` (prompt/completion/total). Omit when empty.
- Prefer doing **less** work over micro-tuning latency — family [MULTI_AGENT_OPTIMIZATION.md](https://github.com/koten-ai/zeus_client_design/blob/main/docs/multi_agent/MULTI_AGENT_OPTIMIZATION.md). Prefer `zeus_direct` when the unit is pure data; default `ai_process_result=false` on cheap paths.

Orchestrator / advisor LLMs are **not** called by this package (sidecar owns them). Python resolves and forwards `config.llm.roles` / `jobs.run(models=)`.

---

## LLM roles (ZCF-047)

Resolve order (later wins):

```text
config.llm
  ∪ config.llm.roles.<role>
  ∪ config.jobs.models.<role>?
  ∪ jobs.run({ models: … })?
  ∪ unit.llm?                     # workers only
  ∪ jobs.run.models.units.<id>?
```

**A — three keys, three models**

```json
{
  "llm": {
    "api_key_env": "LLM_DEFAULT_KEY",
    "model": "fast-worker",
    "roles": {
      "orchestrator": { "model": "strong-planner", "api_key_env": "LLM_ORCH_KEY" },
      "advisor": { "model": "strong-planner", "api_key_env": "LLM_ADV_KEY" },
      "worker": { "model": "fast-worker", "api_key_env": "LLM_WORKER_KEY" }
    }
  }
}
```

**B — one key, three models**

```json
{
  "llm": {
    "api_key_env": "LLM_API_KEY",
    "model": "fast-worker",
    "roles": {
      "orchestrator": { "model": "strong-planner" },
      "advisor": { "model": "strong-planner" },
      "worker": { "model": "fast-worker" }
    }
  }
}
```

Mode 1 `rt.agent.run_turn` **ignores** `roles` unless a product opts in. `units.agent_turn` uses **worker**. If worker `api_key_env` or `base_url` differs from the process LLM, the runtime builds a temporary OpenAI-compatible client from the env **name** (never logs the secret).

---

## Setup runbook (EXAMPLE §0 → SDK)

| EXAMPLE §0 Must | Python |
| --- | --- |
| goal / pack / budgets / unit map | `rt.jobs.run(goal, pack=, budgets=, units=)` |
| `llm.roles` resolvable | `config.llm.roles.*` + `jobs.run(models=)` |
| per-unit id / kind / isolation | `UnitConfig` + `validate_unit_map` |
| Zeus URL / scope triple / auth | `zeus_url`, `bucket/scope/collection`, `auth_mode` + `password_env`/`token_env`/`username` **names**. Applied on every hop this process executes. |
| agent catalog + pin + inject | `base_id` / `catalog_mode` / `chat_request`; missing → `130011` / `130012`. Live brief borrow is **process Zeus only**; a different `zeus_url` must already carry `## SCOPE BRIEF` or MINI-SCHEMA. |
| worker LLM | `roles.worker` ∪ `unit.llm` ∪ job models |
| Never simple Q&A via jobs | `rt.agent.run_turn` |
| Never secrets on events | `to_public_dict` / journal names only |

Multi-URL jobs: repeat the Zeus block per unit. When *this* process runs the unit, `zeus_url` and auth names override `config.zeus` for that hop. Sidecar-run units use the sidecar’s own map.

---

## Isolation

- No shared `messages[]`.
- No shared durable `session_id` across parallel units (default) — `130013`.
- Handoff = explicit artifacts only (`UnitResult.artifacts`).
- Agent units fail closed without catalog pin + `## SCOPE BRIEF` (or MINI-SCHEMA).
- Secrets are `api_key_env` / `password_env` / `token_env` **names**. Never on JobEvents / Detective / support packs.

---

## Errors (`130000–139999`)

| Code | Meaning |
| --- | --- |
| `130001` | multi-agent unavailable (no host / not wired / sidecar 5xx) |
| `130002` | invalid unit map / missing scope |
| `130003` | budget invalid |
| `130004` | job not found |
| `130005` | watch transport / malformed SSE |
| `130010` | unit failure rolled into job |
| `130011` | agent unit missing catalog |
| `130012` | agent unit missing required inject |
| `130013` | isolation violation (shared session) |

13xxxx is **not** SDK-auto-retryable.

---

## Rewind

Unit hops reuse Mode 1/2 header law: `X-Zeus-Chat-Id` / `Turn-Id` / `Trace-Class` (`agent` or `direct.read`). Never set `X-Zeus-Req-Id`. Do not invent a `jobs` Trace-Class. Gather/Detective on `TurnResult.debug` come free from `run_turn`.

---

## Non-goals

- Reimplement RunJob / waves / replan / store / chaos
- Embed `koten_multi_agent_golang`
- `http_json` units, WS/gRPC watch, callback server
- MATRIX `demo` / `supported` from fakes or CI
- ZCM-065 agent graphs
- A Python cost ledger

---

## Claim ladder

```text
2.0.0          → multi_agent = no
2.1.0          → docs (seam)
this train     → docs (CHECKLIST F closeout: runbook hops + roles applied + events/cost/budget)
next           → demo   (compose against live sidecar + fruit-beer EXAMPLE + distinct orch vs worker model ids)
human only     → supported
```

`examples/multi_agent_units.py` uses **FakeJobRuntime** and is **not** a MATRIX demo.

Blocked for `demo` until sidecar clone + live WatchJob **and** a real RunJob host + distinct orch vs worker model ids on the job (CHECKLIST §F last spirit).
