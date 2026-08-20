# Multi-agent Pattern B (Python jobs/units seam) Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
>
> **Mode:** Planning only in the authoring turn — no implementation until execution is approved.
>
> **SoT hierarchy (do not invent outside this):**
> 1. Family law — `zeus_client_design` HOW_TO P-Jobs · CHECKLIST §F · `docs/multi_agent/*` · `guides/api/API_JOBS.md` · `API_UNITS.md` · `API_CONFIG.md` §7.6 · `API_ERROR_CODES.md` `130000–139999` · ZCF-WISH-040…047
> 2. Package layout — `zeus_client_python/docs/V2/IMPLEMENTATION_GUIDE.md` (module tree / TDD) + existing hexagonal `ZeusRuntime`
> 3. Product intent — `MICHAEL_WISHLIST.md` **does not own** multi-agent (link only). Python *consumes* the family jobs runtime; do **not** dual-list a new `ZCM-WISH-*`.
>
> **Board:** **ZCP** only (package). New epic after ZCP-63. Never reuse Token (23–32), GA (33–44), or Detective (45–63) keys. Never file this on ZC/ZD.

**Goal:** Make `kotenai-zeus-client` **multi-agent ready at MATRIX `docs`**: a thin Pattern-B seam (`rt.jobs.*` + `rt.units.*` + `config.llm.roles`) that composes with `koten_multi_agent_golang` — without embedding or reimplementing the job engine.

**Architecture:** Keep the journaled hexagonal runtime. Mode 1 (`rt.agent`) and Mode 2 (`rt.data`) stay the only Zeus tool planes. Mode 3 is **optional**: `UnitsAPI` wraps those planes with isolation + worker LLM resolve; `JobsAPI` is a **port** whose production adapter is HTTP/SSE to a sidecar (Pattern B). A **test-only** `FakeJobRuntime` seeds suite L4 (ordered events, isolation, partial, cancel) and must never be used to claim MATRIX `demo`/`supported`. Single-agent chat never routes through jobs.

**Tech Stack:** Python 3.11+, existing `ZeusRuntime` / `httpx` / `respx` / pytest; no new runtime dependency on Go; no FFI.

---

## 0. Locked decisions (do not re-litigate)

| Decision | Lock |
| --- | --- |
| Integration pattern | **B · sidecar / service** (HOW_TO + MULTI_AGENT.md). Pattern A is Go. Pattern C (native orchestrator) and D (FFI) are **out**. |
| What this package owns | **Layer C — Client law inside units** + thin `jobs.*` client. Layer A (replan/waves/store/chaos) stays in `koten_multi_agent_golang`. Layer B (durable Zeus jobs HTTP) stays in Zeus. |
| Claim this train | **`multi_agent=docs`**. `demo` needs a runnable job **runtime** (Go sidecar), not fakes — LL-2026-07: *never claim product multi-agent with fakes only*. `supported` is a **human** MATRIX award. |
| Version | Bump to **`2.1.0`** when the public seam lands (new optional Mode 3 surface). Keep `claim_level=candidate`. **Keep `zeus_client_v2` alias** — removal slips to **≤2.2.0** (yelp still imports `_v2`). |
| Simple Q&A | Still `rt.agent.run_turn`. **Never** auto-promote one-scope chat into `jobs.run`. |
| Roles vs single-agent | `config.llm.roles` is **ignored** by Mode 1 unless a product explicitly opts in. Units default to **worker**. |
| Catalogs vs models | Orthogonal (EXAMPLE §1). `chat_request` is only for `agent_turn`. Orchestrator/advisor need **no** Zeus catalog. |
| Isolation | No shared `messages[]`. No shared durable `session_id` across parallel units (default). Handoff = explicit artifacts only. |
| Stamps | Never invent `contract_hash`. Agent units fail closed without stamped catalog + required inject. |
| Secrets | `api_key_env` **names** only. Never log values. Never put secrets on JobEvents / Detective / support packs. |
| Transports this train | **SSE watch only**. WS (P8) / gRPC (P9) are follow-ups. |
| `http_json` unit | **YAGNI** this train — raise `000002` if asked. Packs stay in the Go runtime. |
| ZCM-065 graphs | **Not this train.** Declarative agent graphs ≠ family jobs. |
| Dirty tree | `main` is clean vs origin (Rewind ZCP-76…84 + E2E gather ZCP-85 landed). Implement on **`feat/ZCP-multi-agent-pattern-b` from `origin/main`**. Do not add untracked `.hermes/wip/` or `detective-session-data.json`. |
| Jira | After this plan is approved and user asks for tickets: Epic + one Story per task below on **ZCP**. |

### Out of scope (explicit)

- Reimplement RunJob / waves / replan / result-store CAS / chaos / checkpoint
- Embed or vendor `koten_multi_agent_golang`
- Force Hub Debug Chat to become a multi-agent desk
- Public `run_pipeline` / Direct pipeline
- Unit-callback HTTP server (sidecar → Python units) — open question #3; defer
- WS / gRPC watch
- MATRIX `supported` / pins flip / COMPAT forge
- Demo Travel/Yelp/sample UI work (ZD/ZC)
- Dual-listing ZCF-040…047 as new ZCM rows

### Claim ladder (honesty)

```text
today          → multi_agent = no
this train     → docs   (seam + roles + units + jobs port + HTTP/SSE adapter + package docs)
next train     → demo   (compose/README against live koten_multi_agent_golang sidecar)
human only     → supported
```

---

## 1. Context (as found 2026-08-14)

### 1.1 Package

| Fact | Value |
| --- | --- |
| Version / import | `2.0.0` · `import zeus_client` = `ZeusRuntime` |
| Facades today | `rt.agent` · `rt.data` · `rt.catalog` · `rt.debug` — **no** `jobs` / `units` |
| `LlmProviderConfig` | Single slice (`model`, `api_key_env`). **No** `roles` |
| `DataAPI.verb` | Always uses `rt.config.target` — **blocks** multi-scope units until `target=` is added |
| `AgentAPI.run_turn` | Already accepts `target=`, `model=`, `session=`, `chat_request=` — enough for isolated agent units |
| `ErrorCode` | No `13xxxx` band yet |
| Public freeze | `tests/unit/test_public_api_exports.py` exact `__all__` |
| MATRIX (package README) | `multi_agent = no` · modes `agent, direct` only |
| Local design MATRIX | Still shows Python `0.1.x` / `multi_agent=no` — honesty refresh is a **design-repo** follow-up, not this package PR |

### 1.2 Family L0 (implement exactly)

```text
rt.jobs.run(goal, pack?, budgets, scope_map|units, models?)
rt.jobs.watch(job_id, after_seq?)     # SSE now
rt.jobs.get(job_id)
rt.jobs.cancel(job_id)

rt.units.agent_turn(...)   → Mode 1 AgentTurn (worker LLM, isolated bags)
rt.units.zeus_direct(...)  → Mode 2 DataVerb (no LLM, no catalog)
```

Errors (API_JOBS / API_UNITS / API_ERROR_CODES §14c):

| Code | Meaning |
| --- | --- |
| `130001` | multi-agent unavailable (no host / not wired) |
| `130002` | invalid unit map / missing scope |
| `130003` | budget invalid |
| `130004` | job not found |
| `130005` | watch transport fail |
| `130010` | unit failure rolled into job (nest unit code) |
| `130011` | agent unit missing catalog/pin |
| `130012` | agent unit missing required inject |
| `130013` | isolation violation (shared messages / shared session) |

### 1.3 LLM resolve order (normative, later wins)

```text
config.llm
  ∪ config.llm.roles.<role>          # orchestrator | advisor | worker
  ∪ config.jobs.models.<role>?
  ∪ jobs.run({ models: … })?
  ∪ unit.llm?                        # workers only
  ∪ jobs.run.models.units.<id>?
```

Log resolved **`model` + role + `api_key_env` name**. Never the secret.

### 1.4 Sidecar HTTP (Pattern B)

Family docs do **not** freeze REST paths in this repo — they live in `koten_multi_agent_golang`. This train:

1. Defines a **Python DTO + `JobRuntimePort`**.
2. Implements `HttpxJobRuntime` against **constants in one file** (`adapters/jobs_http/paths.py`).
3. Contract-tests with `respx`.
4. Documents: *clone the Go runtime and align paths before any `demo` claim*. If clone paths differ, patch `paths.py` only.

Suggested starting constants (adjust to Go SoT when cloned — do not invent a second protocol):

```text
POST   {host}/v1/jobs
GET    {host}/v1/jobs/{job_id}
POST   {host}/v1/jobs/{job_id}/cancel
GET    {host}/v1/jobs/{job_id}/events?after_seq=   # text/event-stream
```

JobEvent conceptual fields (API_JOBS): `seq`, `type`, `job_id`, `unit_id?`, `ts`, minified payload. **Do not fork names** if the Go schema already uses others — import those names when the clone is present.

---

## 2. Target module tree (IG-compatible)

```text
src/zeus_client/
  api/jobs.py                         # JobsAPI
  api/units.py                        # UnitsAPI
  domain/jobs.py                      # types + isolation + budgets
  domain/llm_roles.py                 # resolve_llm_slice
  application/units_agent.py          # agent_turn use-case wrapper
  application/units_direct.py         # zeus_direct use-case wrapper
  ports/jobs.py                       # JobRuntimePort
  adapters/jobs_http/{__init__,client,paths,sse}.py
  adapters/jobs_fake/runtime.py       # tests + examples only; not default
  config/models.py                    # + LlmRoleConfig, JobsConfig, roles
  config/loader.py                    # parse llm.roles + jobs
  domain/errors.py                    # 13xxxx + JobError
  domain/journal/events.py            # job.* / unit.* constants
  runtime.py                          # rt.jobs / rt.units properties
docs/V2/MULTI_AGENT.md                # package seam (link family docs)
examples/multi_agent_units.py         # offline units demo (not a MATRIX demo)
tests/unit/domain/test_jobs.py
tests/unit/domain/test_llm_roles.py
tests/unit/api/test_units.py
tests/unit/api/test_jobs.py
tests/contract/adapters/test_jobs_http.py
```

Public integrator surface stays facades + a **small** typed set (`JobHandle`, `JobEvent`, `JobBudgets`, `UnitConfig`, `UnitResult`, `LlmRoleConfig`). Demos must **not** import `application.*`.

---

## 3. Step-by-step tasks

### Task 0: Branch and SoT pin

**Objective:** Isolate this train from Detective WIP and pin the design docs.

**Files:** none in package yet.

**Steps:**

1. Confirm dirty Detective files are **not** on this branch:
   ```bash
   git fetch origin
   git checkout -b feat/ZCP-multi-agent-pattern-b origin/main
   git status -sb
   ```
   Expected: clean vs `origin/main`.
2. Re-read (do not rewrite):
   - `../zeus_client_design/docs/multi_agent/MULTI_AGENT.md`
   - `MULTI_AGENT_ZEUS_CLIENT.md` §§2–8, 12–13
   - `guides/api/API_JOBS.md` · `API_UNITS.md` · `API_CONFIG.md` §7.6
   - `HOW_TO_MAKE_A_CLIENT.md` P-Jobs
3. Optional: clone `koten_multi_agent_golang` **read-only** to verify WatchJob paths. If missing, continue with `paths.py` constants and a `docs/V2/MULTI_AGENT.md` “blocked for demo” note.

**Commit:** none (or empty branch push only if asked).

---

### Task 1: Error codes `130001`–`130013`

**Objective:** Family 13-band exists and is typed.

**Files:**
- Modify: `src/zeus_client/domain/errors.py`
- Test: `tests/unit/domain/test_errors.py`

**Step 1: Write failing test**

```python
def test_multi_agent_error_band_130001_through_130013() -> None:
    assert ErrorCode.JOBS_UNAVAILABLE.value == "130001"
    assert ErrorCode.JOBS_INVALID_UNIT_MAP.value == "130002"
    assert ErrorCode.JOBS_BUDGET_INVALID.value == "130003"
    assert ErrorCode.JOBS_NOT_FOUND.value == "130004"
    assert ErrorCode.JOBS_WATCH_FAILED.value == "130005"
    assert ErrorCode.JOBS_UNIT_FAILED.value == "130010"
    assert ErrorCode.UNITS_CATALOG_MISSING.value == "130011"
    assert ErrorCode.UNITS_INJECT_MISSING.value == "130012"
    assert ErrorCode.UNITS_ISOLATION.value == "130013"
    err = JobError(code=ErrorCode.JOBS_UNAVAILABLE, component="api.jobs")
    assert err.retryable is False
    assert "130001" in str(err)
```

**Step 2:** `pytest tests/unit/domain/test_errors.py::test_multi_agent_error_band_130001_through_130013 -v`  
Expected: FAIL — `JOBS_UNAVAILABLE` missing.

**Step 3: Minimal implementation**

Add enum members + `_PUBLIC_MESSAGES` + class:

```python
class JobError(ZeusClientError):
    """Mode 3 jobs/units failures (130000–139999)."""
```

Do **not** mark 13xxxx retryable (job recovery is replan/partial/abort, not SDK auto-retry).

**Step 4:** same pytest — PASS.

**Step 5: Commit**

```bash
git add src/zeus_client/domain/errors.py tests/unit/domain/test_errors.py
git commit -m "feat(jobs): add family error band 130001-130013 (ZCP-N)"
```

---

### Task 2: Domain job / unit types

**Objective:** Frozen dataclasses matching L0 inputs/outputs (no HTTP).

**Files:**
- Create: `src/zeus_client/domain/jobs.py`
- Test: `tests/unit/domain/test_jobs.py`

**Step 1: Failing tests** for construction + `to_public_dict` never includes secrets.

```python
from zeus_client.domain.jobs import (
    JobBudgets,
    JobEvent,
    JobHandle,
    UnitConfig,
    UnitKind,
    UnitResult,
    UnitStatus,
)

def test_unit_config_requires_scope_triple_fields() -> None:
    u = UnitConfig(
        unit_id="u1",
        kind=UnitKind.AGENT_TURN,
        zeus_url="http://127.0.0.1:8080",
        bucket="beer-sample",
        scope="sales",
        collection="_default",
        goal="shortlist fruit beers",
        catalog_mode="analytics",
        base_id="base-5.3",
    )
    assert u.kind is UnitKind.AGENT_TURN
    d = u.to_public_dict()
    assert "password" not in str(d).lower()
    assert "api_key" not in d

def test_job_event_is_minified() -> None:
    ev = JobEvent(seq=1, type="job.started", job_id="j1", ts_ms=1, payload={"status": "accepted"})
    assert ev.unit_id is None
    assert "password" not in ev.to_public_dict()
```

Copy-paste types (complete):

```python
# src/zeus_client/domain/jobs.py
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from zeus_client.config.models import DataTarget

class UnitKind(str, Enum):
    AGENT_TURN = "agent_turn"
    ZEUS_DIRECT = "zeus_direct"
    HTTP_JSON = "http_json"  # not implemented this train

class UnitStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEAD_END = "dead_end"

@dataclass(frozen=True, slots=True)
class JobBudgets:
    max_workers: int = 4
    wall_ms: int = 120_000
    max_waves: int = 4
    max_replans: int = 2
    max_evidence_keys: int = 32
    disable_early_cancel: bool = False

    def validate(self) -> None:
        from zeus_client.domain.errors import ErrorCode, JobError
        if self.max_workers < 1 or self.wall_ms < 1 or self.max_waves < 1:
            raise JobError(
                code=ErrorCode.JOBS_BUDGET_INVALID,
                component="domain.jobs",
                public_message="job budget invalid",
            )

@dataclass(frozen=True, slots=True)
class UnitConfig:
    unit_id: str
    kind: UnitKind
    goal: str
    zeus_url: str | None = None
    bucket: str | None = None
    scope: str | None = None
    collection: str | None = None
    auth_mode: str | None = None
    password_env: str | None = None  # name only
    token_env: str | None = None
    catalog_mode: str | None = None
    base_id: str | None = None
    chat_request: Mapping[str, Any] | None = None
    llm: Mapping[str, Any] | None = None  # partial slice: model / api_key_env / temperature
    call: Mapping[str, Any] | None = None  # zeus_direct {verb, body}
    share_session_id: str | None = None    # default None = new session
    max_rounds: int | None = None

    def target(self) -> DataTarget:
        return DataTarget(
            bucket=self.bucket or "",
            scope=self.scope or "",
            collection=self.collection or "",
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "goal": self.goal,
            "zeus_url": self.zeus_url,
            "bucket": self.bucket,
            "scope": self.scope,
            "collection": self.collection,
            "auth_mode": self.auth_mode,
            "password_env": self.password_env,
            "token_env": self.token_env,
            "catalog_mode": self.catalog_mode,
            "base_id": self.base_id,
            "llm": {
                k: v
                for k, v in dict(self.llm or {}).items()
                if k in {"model", "api_key_env", "temperature", "base_url", "provider"}
            },
            "has_chat_request": self.chat_request is not None,
            "share_session_id": bool(self.share_session_id),
        }

@dataclass(frozen=True, slots=True)
class UnitResult:
    unit_id: str
    status: UnitStatus
    answer: str = ""
    req_ids: tuple[str, ...] = ()
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    dead_end: bool = False
    plan_epoch: int = 0

@dataclass(frozen=True, slots=True)
class JobHandle:
    job_id: str
    status: str = "accepted"  # accepted | running | ...
    seq: int = 0

@dataclass(frozen=True, slots=True)
class JobEvent:
    seq: int
    type: str
    job_id: str
    ts_ms: int
    unit_id: str | None = None
    wave: int | None = None
    plan_epoch: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "job_id": self.job_id,
            "ts_ms": self.ts_ms,
            "unit_id": self.unit_id,
            "wave": self.wave,
            "plan_epoch": self.plan_epoch,
            "payload": dict(self.payload),
        }

@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    status: str
    seq: int
    partial: bool = False
    unit_summaries: tuple[Mapping[str, Any], ...] = ()
    answer: str = ""
```

**Step 4:** pytest PASS. **Step 5:** commit `feat(jobs): add Mode 3 domain types`.

---

### Task 3: Isolation + unit-map validation

**Objective:** Fail closed before any Zeus/LLM hop.

**Files:**
- Modify: `src/zeus_client/domain/jobs.py` (add `validate_unit_map`)
- Test: `tests/unit/domain/test_jobs.py`

**Failing tests:**

```python
from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import UnitConfig, UnitKind, validate_unit_map

def test_missing_scope_is_130002() -> None:
    units = [
        UnitConfig(unit_id="u1", kind=UnitKind.ZEUS_DIRECT, goal="x", zeus_url="http://z"),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.JOBS_INVALID_UNIT_MAP

def test_agent_missing_catalog_is_130011() -> None:
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.AGENT_TURN,
            goal="x",
            zeus_url="http://z",
            bucket="b",
            scope="s",
            collection="c",
        ),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.UNITS_CATALOG_MISSING

def test_shared_session_across_units_is_130013() -> None:
    shared = "sess_shared"
    units = [
        UnitConfig(
            unit_id="u1", kind=UnitKind.ZEUS_DIRECT, goal="a",
            zeus_url="http://z", bucket="b", scope="s", collection="c",
            share_session_id=shared,
        ),
        UnitConfig(
            unit_id="u2", kind=UnitKind.ZEUS_DIRECT, goal="b",
            zeus_url="http://z", bucket="b", scope="east", collection="c",
            share_session_id=shared,
        ),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.UNITS_ISOLATION

def test_duplicate_unit_id_is_130002() -> None:
    ...
```

**Implementation sketch:**

```python
def validate_unit_map(units: list[UnitConfig]) -> None:
    if len(units) < 1:
        raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="domain.jobs")
    seen: set[str] = set()
    sessions: dict[str, str] = {}
    for u in units:
        if not u.unit_id or u.unit_id in seen:
            raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="domain.jobs")
        seen.add(u.unit_id)
        if u.kind is UnitKind.HTTP_JSON:
            raise JobError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="domain.jobs",
                public_message="http_json units are not implemented in this SDK train",
            )
        if not u.zeus_url or not u.bucket or not u.scope or not u.collection:
            raise JobError(code=ErrorCode.JOBS_INVALID_UNIT_MAP, component="domain.jobs")
        if u.kind is UnitKind.AGENT_TURN:
            if not (u.base_id or u.catalog_mode or u.chat_request):
                raise JobError(code=ErrorCode.UNITS_CATALOG_MISSING, component="domain.jobs")
        if u.share_session_id:
            prev = sessions.get(u.share_session_id)
            if prev and prev != u.unit_id:
                raise JobError(code=ErrorCode.UNITS_ISOLATION, component="domain.jobs")
            sessions[u.share_session_id] = u.unit_id
```

Inject presence (`130012`) is checked later in `units.agent_turn` after catalog load (need actual brief markers).

**Commit:** `feat(jobs): validate unit map isolation and required fields`

---

### Task 4: `config.llm.roles` + `config.jobs`

**Objective:** Normative multi-role config is loadable; secrets stay names.

**Files:**
- Modify: `src/zeus_client/config/models.py`
- Modify: `src/zeus_client/config/loader.py`
- Modify: `src/zeus_client/config/__init__.py` (export `LlmRoleConfig`, `JobsConfig`)
- Test: `tests/unit/domain/test_config.py`

**Failing test:**

```python
def test_load_llm_roles_and_jobs_host(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(
        json.dumps(
            {
                "llm": {
                    "model": "fast-worker",
                    "api_key_env": "LLM_DEFAULT_KEY",
                    "roles": {
                        "orchestrator": {"model": "strong-planner", "api_key_env": "LLM_ORCH_KEY"},
                        "advisor": {"model": "strong-planner"},
                        "worker": {"model": "fast-worker", "api_key_env": "LLM_WORKER_KEY"},
                    },
                },
                "jobs": {
                    "host_url": "http://127.0.0.1:7090",
                    "models": {"worker": {"model": "fast-worker-v2"}},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_runtime_config(p, profile="development", env={})
    assert cfg.llm.roles["orchestrator"].model == "strong-planner"
    assert cfg.llm.roles["orchestrator"].api_key_env == "LLM_ORCH_KEY"
    assert cfg.llm.roles["advisor"].api_key_env == "LLM_DEFAULT_KEY"  # inherit default name
    assert cfg.jobs.host_url == "http://127.0.0.1:7090"
    pub = cfg.to_public_dict()
    assert pub["llm"]["roles"]["orchestrator"]["api_key_env"] == "LLM_ORCH_KEY"
    assert "sk-" not in json.dumps(pub)
    assert "api_key" not in json.dumps(pub["llm"])
```

**Models to add** (frozen, env-name only):

```python
@dataclass(frozen=True, slots=True)
class LlmRoleConfig:
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    provider: str | None = None
    temperature: float | None = None

    def __repr__(self) -> str:
        return (
            f"LlmRoleConfig(model={self.model!r}, api_key_env={self.api_key_env!r}, "
            f"base_url={self.base_url!r}, provider={self.provider!r}, "
            f"temperature={self.temperature!r})"
        )

@dataclass(frozen=True, slots=True)
class JobsConfig:
    host_url: str | None = None
    watch_transport: Literal["sse"] = "sse"
    models: Mapping[str, Any] = field(default_factory=dict)

# LlmProviderConfig: add
roles: Mapping[str, LlmRoleConfig] = field(default_factory=dict)

# RuntimeConfig: add
jobs: JobsConfig = field(default_factory=JobsConfig)
```

Loader: parse `llm.roles` object; unknown role names allowed but only `orchestrator|advisor|worker` are used by resolve. Parse `jobs.host_url` / `jobs.models`. Extend `to_public_dict` with roles + jobs.host_url (no secrets).

Env overlay (optional, YAGNI unless cheap): `ZEUS_CLIENT_JOBS_HOST_URL`.

Single-agent tests must still pass — missing `roles`/`jobs` ⇒ empty defaults.

**Commit:** `feat(config): llm.roles and jobs.host_url (ZCF-047)`

---

### Task 5: `resolve_llm_slice`

**Objective:** Pure later-wins resolve; no I/O.

**Files:**
- Create: `src/zeus_client/domain/llm_roles.py`
- Test: `tests/unit/domain/test_llm_roles.py`

```python
# resolve order tests — one test per layer
def test_worker_inherits_default_then_role_then_unit() -> None:
    from zeus_client.config.models import LlmProviderConfig, LlmRoleConfig, JobsConfig
    from zeus_client.domain.llm_roles import LlmRole, resolve_llm_slice

    base = LlmProviderConfig(
        model="fast-worker",
        api_key_env="LLM_DEFAULT_KEY",
        roles={
            "worker": LlmRoleConfig(model="fast-worker", api_key_env="LLM_WORKER_KEY"),
            "orchestrator": LlmRoleConfig(model="strong-planner", api_key_env="LLM_ORCH_KEY"),
        },
    )
    got = resolve_llm_slice(
        base,
        role=LlmRole.WORKER,
        jobs=JobsConfig(models={"worker": {"model": "fast-worker-v2"}}),
        job_models={"units": {"u1": {"model": "fast-worker-v3"}}},
        unit_llm={"temperature": 0.1},
        unit_id="u1",
    )
    assert got.model == "fast-worker-v3"
    assert got.api_key_env == "LLM_WORKER_KEY"
    assert got.temperature == 0.1
    assert got.role == "worker"
    pub = got.to_public_dict()
    assert set(pub) >= {"role", "model", "api_key_env"}
    assert "api_key" not in pub
```

Also: orchestrator resolve **ignores** `unit.llm`. Empty roles ⇒ default `config.llm`.

**Commit:** `feat(jobs): resolve llm.roles later-wins order`

---

### Task 6: Journal constants for job/unit lifecycle

**Objective:** Minified job/unit events can be appended without new schema version.

**Files:**
- Modify: `src/zeus_client/domain/journal/events.py`
- Test: existing journal unit tests + a small new assertion

Add:

```python
EVENT_JOB_STARTED = "job.started"
EVENT_JOB_FINISHED = "job.finished"
EVENT_UNIT_STARTED = "unit.started"
EVENT_UNIT_FINISHED = "unit.finished"
```

Data keys allowed on hot events: `job_id`, `unit_id`, `wave`, `plan_epoch`, `status`, `llm.role`, `llm.model`, `req_id` — **no** bodies, **no** secrets. Full unit payloads stay off the event (store/result path).

**Commit:** `feat(journal): job and unit lifecycle event types`

---

### Task 7: `DataAPI.verb(..., target=)` (multi-scope Direct)

**Objective:** Mode 2 can hit a per-unit `DataTarget` without mutating process config.

**Files:**
- Modify: `src/zeus_client/api/data.py`
- Test: `tests/unit/api/test_data.py` (create if missing) or extend existing data tests

**Failing test:** fake Zeus port records `VerbRequest.target`; call `rt.data.find({...}, target=DataTarget(bucket="east", ...))` and assert recorded target ≠ `rt.config.target`.

Default remains `rt.config.target` (no behavior change for Travel/Yelp).

**Commit:** `feat(data): optional per-call DataTarget for multi-scope units`

---

### Task 8: `UnitsAPI.agent_turn`

**Objective:** One isolated Mode 1 turn with worker LLM + correlation.

**Files:**
- Create: `src/zeus_client/application/units_agent.py`
- Create: `src/zeus_client/api/units.py`
- Test: `tests/unit/api/test_units.py`

**Failing test (scripted LLM + fake Zeus, pattern from `tests/unit/api/test_agent_brief_borrow.py`):**

```python
@pytest.mark.asyncio
async def test_agent_turn_unit_uses_worker_model_and_own_session():
    # 1) two sequential units must not share session_id (enable_sessions=False default)
    # 2) llm.complete sees model == resolved worker model
    # 3) result.req_ids collected from debug / hops
    # 4) missing inject on catalog without ## SCOPE BRIEF → 130012
```

**Implementation (wrapper, not a second loop):**

```python
# api/units.py
class UnitsAPI:
    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    async def agent_turn(
        self,
        unit: UnitConfig,
        *,
        job_id: str | None = None,
        wave: int | None = None,
        plan_epoch: int = 0,
        job_models: Mapping[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> UnitResult:
        ...
```

Rules:

1. `validate_unit_map([unit])`.
2. If `cancel_event` is set → `UnitStatus.CANCELLED` (honor ctx cancel; MULTI_AGENT_RUNTIME §3.5).
3. Load catalog via `rt.catalog.load(mode=unit.catalog_mode or settings.mode, ...)` when `chat_request` omitted. If required inject missing (`## SCOPE BRIEF` absent and borrow failed) → `130012`.
4. Resolve worker slice; pass `model=slice.model` into `rt.agent.run_turn`.
5. If `slice.api_key_env` ≠ process default, construct a **temporary** `OpenAICompatibleLlmClient` with that env name (do not log the value). If constructing adapters from `api/units.py` feels leaky, put the factory in `application/units_agent.py`.
6. `session=None` unless `share_session_id` set (and validation already forbade sharing across units).
7. `enable_sessions` default **False** for units (EXAMPLE: durable usually off). Product can opt in later.
8. Append journal `unit.started` / `unit.finished` with `job_id`, `unit_id`, `llm.role=worker`, `llm.model`.
9. Peel stays on `TurnResult.answer` (existing G2 law). Chat bubble = answer only.
10. Map `TurnStatus.ERROR` → `UnitStatus.ERROR` with nested code; never raise out of a unit into the job process if called from FakeJobRuntime (return structured status). Public `units.agent_turn` **may** raise `JobError` for validation; execution failures return `UnitResult(status=error)`.

**Commit:** `feat(units): agent_turn wraps Mode 1 with isolation`

---

### Task 9: `UnitsAPI.zeus_direct`

**Objective:** One isolated Mode 2 verb; no catalog, no LLM.

**Files:**
- Create: `src/zeus_client/application/units_direct.py`
- Modify: `src/zeus_client/api/units.py`
- Test: `tests/unit/api/test_units.py`

```python
@pytest.mark.asyncio
async def test_zeus_direct_unit_rejects_pipeline_and_records_req_id():
    # unit.call = {verb: "pipeline", body: {}} → ZEUS_PIPELINE_NOT_ON_DIRECT nested
    # unit.call = {verb: "find", body: {entity_type: "Beer"}} → ok + req_ids
```

Uses Task 7 `rt.data.verb(name, body, target=unit.target())`. Missing `call.verb` → `130002`.

**Commit:** `feat(units): zeus_direct wraps Mode 2 DataVerb`

---

### Task 10: `JobRuntimePort` + `JobsAPI` (fail closed without host)

**Objective:** L0 `jobs.*` exists; no host ⇒ `130001`.

**Files:**
- Create: `src/zeus_client/ports/jobs.py`
- Create: `src/zeus_client/api/jobs.py`
- Modify: `src/zeus_client/runtime.py` (`rt.jobs`, `rt.units`; optional `services.jobs`)
- Test: `tests/unit/api/test_jobs.py`

Port:

```python
# ports/jobs.py
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

@runtime_checkable
class JobRuntimePort(Protocol):
    async def run(self, request: Mapping[str, Any]) -> JobHandle: ...
    def watch(self, job_id: str, *, after_seq: int = 0) -> AsyncIterator[JobEvent]: ...
    async def get(self, job_id: str) -> JobSnapshot: ...
    async def cancel(self, job_id: str) -> JobSnapshot: ...
```

`JobsAPI.run`:

1. Parse `units` / `scope_map` → `list[UnitConfig]`.
2. `JobBudgets.validate()` + `validate_unit_map`.
3. If `self._rt.services.jobs is None` and no `config.jobs.host_url` → `130001`.
4. Else call port. Do **not** execute units in `JobsAPI` (sidecar/fake owns scheduling).
5. Journal `job.started`.

`watch` / `get` / `cancel` same unavailable path.

Wire `rt.jobs` / `rt.units` properties like existing facades.

**Commit:** `feat(jobs): JobsAPI fail-closed without runtime host`

---

### Task 11: Test-only `FakeJobRuntime`

**Objective:** L4 seed — ordered events, isolation, partial success, cancel. **Not** a product orchestrator (no LLM planner, no replan engine).

**Files:**
- Create: `src/zeus_client/adapters/jobs_fake/runtime.py`
- Test: `tests/unit/api/test_jobs.py`

Behavior (deliberately dumb):

1. `run` assigns `job_id`, status `running`.
2. Executes units **in input order** via `UnitsAPI` (sequential is enough for isolation tests; optional `asyncio.gather` capped by `max_workers` if cheap).
3. Emits events `seq=1,2,…` : `job.started`, per-unit start/finish, `job.finished`.
4. One unit error ⇒ job snapshot `partial=True` (do not abort siblings unless `cancel` set).
5. `cancel` sets an `asyncio.Event` so in-flight `agent_turn` returns `cancelled`.
6. **No** orchestrator/advisor LLM calls.
7. Not constructed by `ZeusRuntime.from_config`. Tests / examples pass `jobs=FakeJobRuntime(rt)` into `ZeusRuntime(...)`.

Tests:

- two `zeus_direct` fakes → two different targets recorded
- one fail + one ok → `partial=True`, both events present
- `cancel` mid-watch → `cancelled` status, monotonic `seq`
- shared messages cannot be smuggled (validation already)

**Commit:** `test(jobs): FakeJobRuntime L4 seed (not a product engine)`

---

### Task 12: HTTP/SSE sidecar adapter

**Objective:** Pattern B client of a job host.

**Files:**
- Create: `src/zeus_client/adapters/jobs_http/paths.py`
- Create: `src/zeus_client/adapters/jobs_http/client.py`
- Create: `src/zeus_client/adapters/jobs_http/sse.py`
- Test: `tests/contract/adapters/test_jobs_http.py`

**Contract tests (`respx`):**

1. `run` POST JSON `{goal, pack, budgets, units, models}` → `{job_id, status, seq}`.
2. 503 / connection error → `130001`.
3. 404 get → `130004`.
4. SSE body:

   ```text
   data: {"seq":1,"type":"job.started","job_id":"j1","ts":0}

   data: {"seq":2,"type":"job.finished","job_id":"j1","ts":1}
   ```

   `watch` yields two `JobEvent`s in order; resume `after_seq=1` skips first.
5. Malformed SSE → `130005`.
6. Request JSON must **not** contain raw `api_key` / password values (only `_env` names).

If Go clone is present, update `paths.py` + DTO field names to match. If not, document the assumed paths in `docs/V2/MULTI_AGENT.md` and keep tests on those constants.

**Wiring:** `ZeusRuntime.from_config` constructs `HttpxJobRuntime` **only when** `config.jobs.host_url` is set. Otherwise `services.jobs` stays `None` (`130001`).

**Commit:** `feat(jobs): HTTP/SSE JobRuntimePort adapter (Pattern B)`

---

### Task 13: Public freeze + version `2.1.0`

**Objective:** Integrators can import the Mode 3 types; clocks stay honest.

**Files:**
- Modify: `src/zeus_client/__init__.py` (`__all__` + lazy map)
- Modify: `tests/unit/test_public_api_exports.py`
- Modify: `src/zeus_client/_version.py` + `pyproject.toml` → `2.1.0`
- Modify: `tests/unit/test_smoke_import_v2.py` if it pins `2.0.0`
- Modify: `README.md` claim table (see Task 14)

Add to public freeze (keep small):

```text
JobHandle, JobEvent, JobBudgets, JobSnapshot,
UnitConfig, UnitKind, UnitResult, UnitStatus,
LlmRoleConfig, JobsConfig
```

Do **not** export `FakeJobRuntime`, `HttpxJobRuntime`, or `application.*`.

`test_public_symbols_importable` currently asserts `__version__ == "2.0.0"` — update to `2.1.0`.

**Commit:** `feat: export Mode 3 types and bump 2.1.0`

---

### Task 14: Package docs (claim `docs`)

**Objective:** CHECKLIST §F can be ticked honestly at `docs` — not `demo`.

**Files:**
- Create: `docs/V2/MULTI_AGENT.md`
- Modify: `README.md` claim table: `modes` stay `agent, direct`; add optional Mode 3 note; `multi_agent` → **`docs`**
- Modify: `docs/V2/IMPLEMENTATION_GUIDE.md` tree (`api/jobs.py`, `api/units.py`, adapters)
- Modify: `docs/V2/MIGRATION.md` — new optional section: *Mode 3 is additive; Mode 1/2 unchanged*
- Modify: `docs/V2/T9_TAG_MATRIX_HANDOFF.md` only if it still says “do not claim multi-agent” as a hard forever rule — change to “claim `docs` only after this train; never `supported` from CI”
- Modify: `CHANGELOG.md` (Unreleased / 2.1.0)
- Optional: `examples/multi_agent_units.py` — **offline units** illustration (FakeJobRuntime). README must say this is **not** a MATRIX `demo`.

`docs/V2/MULTI_AGENT.md` must include:

1. Seam diagram (one Mode 1 turn vs one job of many units)
2. How to attach sidecar (`jobs.host_url`)
3. Link family MULTI_AGENT_EXAMPLE §0 runbook
4. `config.llm.roles` examples A/B (from ZEUS_CLIENT §8)
5. Isolation rules
6. Error table 13xxxx
7. Non-goals + claim ladder
8. “Blocked for `demo` until sidecar clone + live WatchJob”

**Commit:** `docs(jobs): Pattern B seam; claim multi_agent=docs`

---

### Task 15: Design-repo honesty (separate PR, after package lands)

**Objective:** Family MATRIX/CHECKLIST match reality. **Do not** edit design repo in the package PR.

**Files (in `zeus_client_design`, later):**
- `MATRIX.md` Python `multi_agent` → `docs` (and version clock if still stale `0.1.x`)
- Do **not** self-award `supported`
- Do **not** invent COMPAT triples

This is a follow-up human/design PR. Package train is done without it.

---

### Task 16: Verification (definition of done)

**Required (package):**

```bash
make ci
# or: pytest -q -m "not integration" && ruff check src tests && mypy
```

Must cover:

- 13xxxx codes + JobError
- unit-map isolation / missing catalog / invalid budget
- llm.roles load + public_dict redaction + resolve order
- `DataAPI` per-call target
- `units.agent_turn` / `zeus_direct` with fakes
- `jobs.*` → `130001` without host
- FakeJobRuntime partial + cancel + monotonic seq
- HTTP/SSE adapter respx
- public `__all__` freeze + `__version__ == 2.1.0`
- existing ~239+ suite still green (count will rise)

**Grep guards:**

```bash
rg -n "koten_multi_agent_golang" src || true   # docs/comments only; no import
rg -n "contract_hash.*=.*md5" src/zeus_client  # must be empty
rg -n "from zeus_client.application" examples  # must be empty
```

**Must not:**

- Claim `demo` / `supported`
- Flip `claim_level`
- Auto-tag / push / PyPI
- Route Mode 1 tests through `jobs.run`

---

## 4. Next train (not this plan) — MATRIX `demo`

Only after Task 16 is green **and** `koten_multi_agent_golang` is runnable:

1. Clone runtime; align `adapters/jobs_http/paths.py` to real WatchJob.
2. Compose: sidecar + Zeus + this client example (fruit-beer EXAMPLE: U1 sales + U2 inventory + merge).
3. Prove distinct orch vs worker **model ids** on the job (CHECKLIST §F last tick).
4. Demo README; then MATRIX `demo` in design repo.
5. Still not `supported`.

---

## 5. Files likely to change (checklist)

| Path | Action |
| --- | --- |
| `src/zeus_client/domain/errors.py` | 13xxxx + `JobError` |
| `src/zeus_client/domain/jobs.py` | types + validation |
| `src/zeus_client/domain/llm_roles.py` | resolve |
| `src/zeus_client/domain/journal/events.py` | job/unit event names |
| `src/zeus_client/config/models.py` | roles + jobs |
| `src/zeus_client/config/loader.py` | parse |
| `src/zeus_client/api/data.py` | `target=` |
| `src/zeus_client/api/units.py` | new |
| `src/zeus_client/api/jobs.py` | new |
| `src/zeus_client/application/units_*.py` | new |
| `src/zeus_client/ports/jobs.py` | new |
| `src/zeus_client/adapters/jobs_http/*` | new |
| `src/zeus_client/adapters/jobs_fake/*` | new (tests) |
| `src/zeus_client/runtime.py` | facades |
| `src/zeus_client/__init__.py` | public freeze |
| `src/zeus_client/_version.py` + `pyproject.toml` | 2.1.0 |
| `docs/V2/MULTI_AGENT.md` | new |
| `README.md` · `CHANGELOG.md` · IG · MIGRATION | claim `docs` |
| `tests/unit/domain/test_{errors,jobs,llm_roles,config}.py` | TDD |
| `tests/unit/api/test_{units,jobs,data}.py` | TDD |
| `tests/contract/adapters/test_jobs_http.py` | TDD |
| `tests/unit/test_public_api_exports.py` | freeze |

**Unchanged by design:** Detective deep-dive, session-trace projector, Travel/Yelp BFFs, catalog fail-closed path law, Layer A peel, Direct pipeline ban.

---

## 6. Risks, tradeoffs, open questions

| Risk | Mitigation |
| --- | --- |
| Temptation to write a Python orchestrator so tests “look like multi-agent” | FakeJobRuntime is sequential/capped gather only; no planner LLM. Docs forbid `demo` on fakes. |
| Sidecar REST paths unknown without Go clone | Isolate in `paths.py`; contract tests pin constants; demo blocked until aligned. |
| `DataAPI` target hole silently uses process default | Task 7 first; units tests assert recorded target. |
| Worker key ≠ default key | Temporary LLM adapter from env **name**; never put key on UnitConfig. |
| Public freeze churn | Additive types only; no removals. |
| Dirty Detective WIP on `main` | Branch from `origin/main`. |
| Design MATRIX still `0.1.x` locally | Separate design PR; do not block package on it. |
| Open Q: sidecar units in Go vs callback to Python | This train: sidecar owns units **or** Python Fake owns units. No callback server. |
| Open Q: suite L4 live vs fakes | Fakes first (family prefers). Live L4 is `demo` train. |
| Open Q: provider diversity | v1 OpenAI-compatible only (ZEUS_CLIENT §14.6). |

---

## 7. Principles enforced

- **DRY:** units wrap existing AgentTurn / DataVerb; no second loop.
- **YAGNI:** no WS/gRPC, no `http_json`, no callback host, no replan engine, no ZCM-065 graphs.
- **TDD:** every task red → green → commit.
- **G2 / answer-only bubble:** unit answers peeled; job timeline is events, not chat scrap.
- **Fail-closed catalogs + isolation.**
- **Honest MATRIX.** Never self-award `supported`. Never claim `demo` with fakes.
- **Frequent commits** with `ZCP-N` once tickets exist.

---

## 8. Jira map (created 2026-08-14)

Board: [ZCP](https://kotenai.atlassian.net/jira/software/projects/ZCP). Status **To Do**. Assignee **Michael Arcega**. Blocks chain ZCP-65 → … → ZCP-75.

| Plan task | Key | Summary |
| --- | --- | --- |
| Epic | [ZCP-64](https://kotenai.atlassian.net/browse/ZCP-64) | Multi-agent Pattern B seam (MATRIX docs) |
| T0 | [ZCP-65](https://kotenai.atlassian.net/browse/ZCP-65) | Branch + SoT pin |
| T1 | [ZCP-66](https://kotenai.atlassian.net/browse/ZCP-66) | Error band 130001-130013 |
| T2–T3 | [ZCP-67](https://kotenai.atlassian.net/browse/ZCP-67) | Domain types + unit-map isolation |
| T4–T5 | [ZCP-68](https://kotenai.atlassian.net/browse/ZCP-68) | `llm.roles` + `resolve_llm_slice` |
| T6 | [ZCP-69](https://kotenai.atlassian.net/browse/ZCP-69) | Journal job/unit events |
| T7 | [ZCP-70](https://kotenai.atlassian.net/browse/ZCP-70) | `DataAPI` per-call target |
| T8–T9 | [ZCP-71](https://kotenai.atlassian.net/browse/ZCP-71) | `units.agent_turn` + `zeus_direct` |
| T10–T11 | [ZCP-72](https://kotenai.atlassian.net/browse/ZCP-72) | JobsAPI + FakeJobRuntime |
| T12 | [ZCP-73](https://kotenai.atlassian.net/browse/ZCP-73) | HTTP/SSE adapter |
| T13–T14 | [ZCP-74](https://kotenai.atlassian.net/browse/ZCP-74) | Public freeze + 2.1.0 + claim `docs` |
| T16 | [ZCP-75](https://kotenai.atlassian.net/browse/ZCP-75) | `make ci` |

**Not on ZCP:** Task 15 (design-repo MATRIX honesty) — follow-up in `zeus_client_design`.

After land: comment SHA + pytest; package stories **Done** (`41`).

---

## 9. Execution handoff

Plan complete and saved. Tickets exist (ZCP-64…75, all To Do). Validated 2026-08-18 — **still executable** with §10 addendum.

Ready to execute task-by-task (TDD, small commits).

---

## 10. Validation addendum (2026-08-18)

Re-checked against `origin/main` @ `327c438` (Rewind ZCP-76…84 + E2E gather ZCP-85) and the local `koten_multi_agent_golang` clone. Architecture, locked decisions, task order, and Jira band **hold**. Do not rewrite the plan — apply these deltas while implementing.

### 10.1 Still true

- No `rt.jobs` / `rt.units` / `llm.roles` / 13xxxx / `JobError` on main.
- `DataAPI.verb` still hard-wires `self._rt.config.target` — T7 still required.
- `AgentAPI.run_turn` still accepts `target=`, `model=`, `session=`, `chat_request=`, `chat_id=`.
- Family 13xxxx table unchanged. Origin MATRIX Python is **2.0.0 / candidate / `multi_agent=no`** (local design checkout may lag — pull before T15).
- ZCP-64…75 still **To Do**; later trains used ZCP-76+.

### 10.2 Version + alias (T13)

`zeus_client_v2` is contracted to die **≤2.1.0** (`MIGRATION.md`, `CHANGELOG`, T9). Yelp still imports the alias.

**Lock for this train:** bump package clocks to **`2.1.0`**, **keep the alias**, and slip removal to **≤2.2.0** in T14 docs. Do **not** delete `src/zeus_client_v2_alias/` here.

### 10.3 Go sidecar HTTP (T0 + T12)

Clone exists at `/home/michael/koten-ai/koten_multi_agent_golang`. Real HTTP today:

```text
GET /v1/jobs/{job_id}/events?from_seq=N    # WatchJob SSE (sampledesk -watch-addr)
```

- Query is **`from_seq`**, not `after_seq`. Also honor `Last-Event-ID`.
- SSE framing: `id: <seq>` / `event: <type>` / `data: <JobEvent JSON>`.
- Go `JobEvent` fields: `schema`, `seq`, `job_id`, `ts` (RFC3339), `type`, `plan_epoch`, `unit_id`, `status`, `stage`, `pct`, `summary`, `trace_id`, `duration_ms`, `dead_end`, `extra`. **Do not fork** to `ts_ms` / `wave` / `payload` if the wire uses these names — map in the adapter.
- `sampledesk` mounts **WatchJob only**. `RunJob` is in-process Go. Zeus `backend/zeus.HTTPClient` is **Layer B** durable jobs (Create/Get/epoch) — **not** client `jobs.run`.

**T12:** implement **watch** against the real SSE path. `run` / `get` / `cancel` stay on `JobRuntimePort` and raise **`130001`** until a real host route exists. **Do not invent `POST /v1/jobs`.** FakeJobRuntime still owns L4. Contract tests pin `paths.py` constants.

### 10.4 Rewind + E2E gather (T7–T9)

ZCP-76…84 stamp `X-Zeus-Chat-Id` / `X-Zeus-Turn-Id` / `X-Zeus-Trace-Class` on every `:8080` hop. ZCP-85 fills nine gather fields on `TurnResult.debug`. Never set or reuse `X-Zeus-Req-Id`. Do not invent a `jobs` Trace-Class.

| Task | Extra law |
| --- | --- |
| T7 `DataAPI.verb(..., target=)` | Keep existing `correlation_headers` (`direct.read`). Default target remains `rt.config.target`. |
| T8 `units.agent_turn` | Pass `chat_id=` (job id, else unit id) into `rt.agent.run_turn`. Gather/Detective come free — do not fork a second debug bag. |
| T9 `units.zeus_direct` | Pass Rewind headers (`direct.read` + chat/turn). Extend `DataAPI.verb` / `run_data_verb` to accept optional `headers=` / `chat_id=` if needed. |

### 10.5 Other stale notes

| Plan said | Now |
| --- | --- |
| Dirty Detective WIP on main | Clean. Branch from `origin/main`. |
| Local MATRIX still `0.1.x` | Origin is B1-honest. T15 only flips `multi_agent` → `docs`. |
| Invent `make ci` | Already shipped (PR #11). T16 is the green gate. |
| Suite ~239 | Count will rise; require default offline suite green, not a fixed number. |

### 10.6 Suggested REST table (supersedes §1.4)

```text
GET    {host}/v1/jobs/{job_id}/events?from_seq=   # implemented this train
POST   {host}/v1/jobs                             # NOT on current sidecar — 130001
GET    {host}/v1/jobs/{job_id}                    # NOT on current sidecar — 130001
POST   {host}/v1/jobs/{job_id}/cancel             # NOT on current sidecar — 130001
```

If the Go clone later grows run/get/cancel routes, patch `paths.py` only.
