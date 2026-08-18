# Multi-agent Pattern B seam (package)

**Claim this release:** `multi_agent = docs`  
**Not claimed:** `demo` (needs a live `koten_multi_agent_golang` sidecar) · `supported` (human MATRIX only)

This package does **not** embed the job engine. Mode 1 (`rt.agent`) and Mode 2 (`rt.data`) stay the only Zeus tool planes. Mode 3 is optional: `rt.units.*` wraps those planes with isolation; `rt.jobs.*` is a port. Production adapter is HTTP/SSE to a sidecar (Pattern B).

Family SoT: `zeus_client_design/docs/multi_agent/*` · `guides/api/API_JOBS.md` · `API_UNITS.md` · `API_CONFIG.md` §7.6.

## One turn vs one job

```text
Mode 1  rt.agent.run_turn(message)     → one chat, one worker LLM, one scope
Mode 3  rt.jobs.run(goal, units=[…])   → many isolated units; sidecar owns waves
        rt.units.agent_turn(unit)      → one Mode 1 turn (worker LLM)
        rt.units.zeus_direct(unit)     → one Mode 2 verb (no LLM, no catalog)
```

Everyday one-scope Q&A stays `rt.agent.run_turn`. Never auto-promote chat into `jobs.run`.

## Attach a sidecar

```json
{
  "jobs": { "host_url": "http://127.0.0.1:7090" },
  "llm": {
    "model": "fast-worker",
    "api_key_env": "LLM_DEFAULT_KEY",
    "roles": {
      "orchestrator": { "model": "strong-planner", "api_key_env": "LLM_ORCH_KEY" },
      "worker": { "model": "fast-worker", "api_key_env": "LLM_WORKER_KEY" }
    }
  }
}
```

`ZeusRuntime.from_config` builds `HttpxJobRuntime` only when `jobs.host_url` is set. Otherwise `rt.jobs.*` raises **`130001`**.

Current Go sidecar HTTP (do not invent the rest):

```text
GET {host}/v1/jobs/{job_id}/events?from_seq=N    # WatchJob SSE
POST /v1/jobs , GET /v1/jobs/{id} , cancel       # NOT on sampledesk — 130001
```

Query param is **`from_seq`**. Event JSON follows Go `JobEvent` (`seq`, `job_id`, `ts`, `type`, `unit_id`, …).

## Isolation

- No shared `messages[]`.
- No shared durable `session_id` across parallel units (default).
- Handoff = explicit artifacts only.
- Agent units fail closed without catalog pin + `## SCOPE BRIEF` (or MINI-SCHEMA).
- Secrets are `api_key_env` **names**. Never on JobEvents / Detective / support packs.

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

## Rewind

Unit hops reuse Mode 1/2 header law: `X-Zeus-Chat-Id` / `Turn-Id` / `Trace-Class` (`agent` or `direct.read`). Never set `X-Zeus-Req-Id`. Do not invent a `jobs` Trace-Class. Gather/Detective on `TurnResult.debug` come free from `run_turn`.

## Non-goals

- Reimplement RunJob / waves / replan / store / chaos
- Embed `koten_multi_agent_golang`
- `http_json` units, WS/gRPC watch, callback server
- MATRIX `demo` / `supported` from fakes or CI
- ZCM-065 agent graphs

## Claim ladder

```text
2.0.0          → multi_agent = no
this train     → docs
next           → demo   (compose against live sidecar + fruit-beer EXAMPLE)
human only     → supported
```

`examples/multi_agent_units.py` uses **FakeJobRuntime** and is **not** a MATRIX demo.

Blocked for `demo` until sidecar clone + live WatchJob + distinct orch vs worker model ids on the job (CHECKLIST §F).
