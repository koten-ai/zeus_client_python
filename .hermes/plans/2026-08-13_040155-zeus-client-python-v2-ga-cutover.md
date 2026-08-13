# Zeus Client Python V2 — Package GA Cutover Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.  
> **Mode:** Planning only in the authoring turn — **no implementation until execution is approved.**  
> **Workspace:** `zeus_client_python` on branch `feat/V2` (package spine — **ZCP** only).  
> **Not this train:** Re-doing ZCP-2…22 spine; sample ZC-56 / Travel ZD-8 BFF features (already dogfood).

**Goal:** Flip default `import zeus_client` from the 0.3.1 free-function tree to the journaled hexagonal V2 runtime, publish package **`2.0.0`**, keep claim honesty until human MATRIX, and migrate remaining monorepo consumers (especially **demo_yelp**) so dual-tree beta can end cleanly.

**Architecture:** Keep dual-tree until the cutover commit, then make **V2 the default import path** (`package-dir` maps `zeus_client` → former `src_v2/zeus_client`). Preserve a **time-boxed** `zeus_client.compat.v1` shim (≤1 minor). V1 source either archives under `src_v1_legacy/` or is deleted once smoke proves no monorepo path still needs the free-function tree. Public DX stays `ZeusRuntime` + typed `TurnResult` / `rt.*`; never `application.*` from demos; never self-award MATRIX `supported`.

**Tech Stack:** Python ≥3.11 · httpx · pytest/pytest-asyncio · respx · setuptools dual→single package-dir · ruff/mypy optional · design suite offline · Jira **ZCP**

---

## Sources of truth (do not invent outside this)

| Priority | Source | Owns |
| --- | --- | --- |
| 1 | `zeus_client_design/HOW_TO_MAKE_A_CLIENT.md` + `docs/autonomy/*` + `CANDIDATE_CHARTER.md` | Family law, G0–G8, claim honesty |
| 2 | `zeus_client_design/docs/MICHAEL/*` + `MICHAEL_WISHLIST.md` | Product intent, ship bands §9, DoD §9.5, public vs internal §9.8 |
| 3 | `docs/V2/{DESIGN,IMPLEMENTATION_GUIDE,MIGRATION,SECURITY,BEST_PRACTICES}.md` | Layout/phase (IG wins), cutover gate, security checklist §23 |
| 4 | Landed consumer BFFs | Travel **ZD-8**; sample **ZC-56** — pattern only |
| 5 | Prior spine plan | `.hermes/plans/2026-08-11_035557-zeus-client-python-v2.md` + skill `references/v2-train.md` |

**Hard rules (copy into every PR):**

1. Never invent production `contract_hash` / Hub stamps.  
2. No `zeus_client.application.*` imports from demos.  
3. No process-global HTTP/auth on V2 paths.  
4. No public Direct `pipeline` / `rt.data.pipeline`.  
5. G2 / scores / `wish_i_knew` never in user-facing `answer`.  
6. `compat.v1` is **migration aid only** — not the final integrator path; remove ≤1 minor after GA.  
7. Do **not** self-award MATRIX `supported` — human design PR only.  
8. Three clocks stay distinct: Zeus engine · BASE `base-N` · package semver **2.0.0**.  
9. Jira for this train: **ZCP** only (not ZC sample board, not ZD demo board for package commits).  
10. Package `ClientSettings.ai_process_result` default remains **True** (Hub); pins may document product-cheap false.

---

## 1. Context (as found)

### 1.1 Package today (`feat/V2` @ `e9095d5`)

| Fact | Value |
| --- | --- |
| Default import | `import zeus_client` → `src/` **0.3.1** free functions |
| V2 import | `import zeus_client_v2` → `src_v2/zeus_client/` **2.0.0b1** |
| `project.version` | **0.3.1** (intentionally frozen during dual-tree) |
| Spine | ZCP-2…ZCP-22 **landed** (Phases 0–8 harden/compat) |
| Claim | `sdk_bootstrap.pins.json` → `claim_level=candidate` |
| Conformance | ZCP-21 offline required green (16/16) |
| Compat | `zeus_client_v2.compat.v1` already exists (deprecated) |
| `py.typed` | Present on V2 tree only |
| Prod profile | Redaction/debug defaults; **does not yet hard-reject** `auth_mode=none` / TLS verify off |
| `pip audit` CI | Deferred (ops) |
| Wishlist statuses | Many Pri-1/2 ZCM still marked `open` despite code land (catalogue lag) |

### 1.2 Cutover gate (MIGRATION.md) — checklist

| # | Gate | Status entering this train |
| --- | --- | --- |
| 1 | Full `pytest -q` green (V1+V2) | **Met** (~656 after ZCP-22) |
| 2 | Conformance offline required | **Met** candidate; MATRIX human still open |
| 3 | One production-shaped demo BFF | **Met ×2** (Travel ZD-8, sample ZC-56 In Review) |
| 4 | SECURITY §23 done or ticketed | **Partial** — tighten prod `auth_mode=none` + ticket/defer `pip audit` |
| 5 | Versions aligned to **2.0.0** | **Not met** |
| 6 | Design MATRIX row (separate PR) | **Not met** — human |

### 1.3 Consumers that still bind V1 default

| Consumer | Board | Import today | Must do before/at cutover |
| --- | --- | --- | --- |
| `demo_yelp` | **ZD** | `zeus_client` 0.3.1 path dep | **Migrate BFF** to native `rt.*` (or pin temporarily — prefer migrate) |
| Travel V2 worktree | ZD-8 | already `zeus_client_v2` | Retest after default flip; drop `_v2` suffix if desired |
| Sample `zeus_client` app | ZC-56 | already `zeus_client_v2` | Retest after default flip |
| Any `file:../zeus_client_python` demo | — | expects 0.3.1 health string | Health → **2.0.0** after cutover |

### 1.4 GA polish band still honest (design §9.1)

Landed in beta (do **not** re-implement): journal, runtime, detective, session-trace, errors, redact, fail-closed catalog, peel, data split, replay/export, retries, profiles, metrics, rate limit, soft hydrate, OTLP stub, compat.

**Still in scope for this GA train (minimal):**

| ZCM | Item | GA action |
| --- | --- | --- |
| 032 | Remove `run_fast_suggest*` | Drop from **V1 tree before archive**; V2 never ships aliases |
| 034 | `py.typed` + public freeze | Ensure default package ships `py.typed`; smoke + optional mypy on `__all__` |
| 036 | Typeahead rate limit | Already ZCP-22 — verify after import flip |
| 040 | SecretStore | Already — verify prod export snapshots |
| — | Prod rejects `auth_mode=none` | **Implement** at cutover (SECURITY §23) |
| 030–031, 041–043 | Hydrate/CLI polish | **Out of minimal cutover** unless already trivial — ticket as post-GA / 2.0.1 |

### 1.5 Packaging end state (locked decision for this plan)

```text
# BEFORE (beta)
package-dir = {zeus_client=src, zeus_client_v2=src_v2/zeus_client}
project.version = 0.3.1
zeus_client_v2.__version__ = 2.0.0b1

# AFTER (GA cutover) — preferred
src/zeus_client/          # V2 tree moved/renamed here (was src_v2/zeus_client)
src_v1_legacy/            # optional archive of 0.3.1 for one minor (not installed) OR delete
compat lives at           # zeus_client.compat.v1 (already under V2 tree)
project.version = 2.0.0
zeus_client.__version__ = 2.0.0
# Optional temporary alias package:
#   zeus_client_v2 → re-export zeus_client with DeprecationWarning for one minor
```

**Rejected:** Leaving dual install forever.  
**Rejected:** Making default import V2 while leaving `project.version=0.3.1`.  
**Rejected:** Using `compat.v1` as the documented happy path.

---

## 2. Target end state

```text
import zeus_client
assert zeus_client.__version__ == "2.0.0"
async with ZeusRuntime.from_config(...) as rt:
    result = await rt.agent.run_turn(...)
# demos: native rt.* only
# health: zeus_client_version == "2.0.0"
# pins: claim_level stays candidate until human MATRIX PR
# design MICHAEL_WISHLIST: Pri-1 + shipped beta rows → done + 2.0.0
# MIGRATION.md: cutover section marked complete; dual-tree section historical
# Tag: v2.0.0 (or 2.0.0) on package repo after green gates
```

---

## 3. Jira map (**created 2026-08-13**)

**Note:** Draft placeholders ZCP-23…32 were already consumed by the Token IN/OUT residual train (**Done**). GA cutover keys start at **ZCP-33**.

| Task | Key | One-liner | Depends |
| --- | --- | --- | --- |
| Epic | [ZCP-33](https://kotenai.atlassian.net/browse/ZCP-33) | Package GA cutover 2.0.0 | ZCP-22 + ZCP-23…32 Done |
| T0 | [ZCP-34](https://kotenai.atlassian.net/browse/ZCP-34) | Preconditions, branch, gate audit | Epic |
| T1 | [ZCP-35](https://kotenai.atlassian.net/browse/ZCP-35) | Wishlist + MIGRATION status hygiene (docs) | T0 |
| T2 | [ZCP-36](https://kotenai.atlassian.net/browse/ZCP-36) | Prod profile reject `auth_mode=none` (+ TLS off) | T0 |
| T3 | [ZCP-37](https://kotenai.atlassian.net/browse/ZCP-37) | Drop V1 `run_fast_suggest*`; freeze public `__all__` tests | T0 |
| T4 | [ZCP-38](https://kotenai.atlassian.net/browse/ZCP-38) | **demo_yelp** V2 BFF blocker tracker (package) | T0; impl **[ZD-20](https://kotenai.atlassian.net/browse/ZD-20)** |
| T5 | [ZCP-39](https://kotenai.atlassian.net/browse/ZCP-39) | Default-import package-dir flip + version 2.0.0 | T2, T3, T4 |
| T6 | [ZCP-40](https://kotenai.atlassian.net/browse/ZCP-40) | Alias `zeus_client_v2` deprecation + V1 archive/delete | T5 |
| T7 | [ZCP-41](https://kotenai.atlassian.net/browse/ZCP-41) | Examples, README, CHANGELOG, MIGRATION final | T5 |
| T8 | [ZCP-42](https://kotenai.atlassian.net/browse/ZCP-42) | Full pytest + consumer smoke + SECURITY checklist | T6, T7 |
| T9 | [ZCP-43](https://kotenai.atlassian.net/browse/ZCP-43) | Tag 2.0.0 + design MATRIX handoff (human) | T8 |
| ops | [ZCP-44](https://kotenai.atlassian.net/browse/ZCP-44) | `pip audit` CI deferred (non-blocking for 2.0.0) | Epic (parallel) |

**Consumer epic:** [ZD-20](https://kotenai.atlassian.net/browse/ZD-20) — demo_yelp BFF → ZeusRuntime (blocks ZCP-38/39).

**Blocks:** T0→T1∥T2∥T3∥T4; (T2∧T3∧T4)→T5→T6∥T7→T8→T9; ZD-20 blocks T4/T5  

**Labels:** `v2`, `ga`, `cutover`, phase `p8-cutover`, ZCM as applicable.  
**Transitions:** package stories → **Done** after green commit + comment (SHA, pytest count).  
**demo_yelp:** implement under **ZD-20**; package **ZCP-38** only tracks “blocker cleared”.

---

## 4. Step-by-step tasks

### Task 0: Preconditions & gate audit (read-only + branch)

**Objective:** Prove green baseline and open the cutover branch before any packaging surgery.

**Files:** none required (optional notes in plan progress table).

**Steps:**

1. Work in package repo:

```bash
cd /home/michael/koten-ai/zeus_client_python
git fetch origin
git checkout feat/V2
git pull --ff-only
git checkout -b feat/ZCP-ga-cutover-2.0.0
```

2. Prove dual-tree baseline:

```bash
. .venv/bin/activate  # or create
pip install -e ".[dev]"
python -c "import zeus_client, zeus_client_v2; print(zeus_client.__version__, zeus_client_v2.__version__)"
# expect: 0.3.1  2.0.0b1
pytest -q
```

3. Confirm consumers exist and note tips:

```bash
test -d /home/michael/koten-ai/demo_yelp
test -d /home/michael/koten-ai/demo_travel_sample
# sample BFF worktree optional
```

4. Fill gate table in PR description (copy §1.2).

**Commit:** none (or empty branch push only if team requires).

**Done when:** branch exists; baseline versions print; full pytest green recorded in ticket comment.

---

### Task 1: Catalogue + docs hygiene (pre-cutover honesty)

**Objective:** Align design wishlist and package MIGRATION narrative with **already shipped** beta so GA doesn’t look like Pri-1 is still open.

**Files:**

- Modify (design repo, separate commit/PR): `zeus_client_design/MICHAEL_WISHLIST.md`  
- Modify: `docs/V2/MIGRATION.md`, `docs/V2/README.md`  
- Modify: skill memory/refs only if statuses change process notes (`references/v2-train.md` after land)

**Steps:**

1. In **design** repo PR (do not block package code on merge if needed, but open PR):

   - Mark shipped spine ZCM-001…012 and landed beta ops (020–029, 033–035, 037, 047 as applicable) → **`done`** + note `2.0.0b1` / pending `2.0.0`.  
   - Leave true residuals open (030 hydrate if unimplemented, 041–043 CLI, 044+ post-GA).  
   - Do **not** invent new ZCM IDs for cutover mechanics.

2. In package `MIGRATION.md`:

   - Add section **“GA cutover train”** pointing at this plan.  
   - Keep cutover gate checklist; mark items that this train will flip.  
   - State: claim remains `candidate` until human MATRIX.

**Tests:** docs-only — no pytest required.

**Commit:**

```bash
git add docs/V2/MIGRATION.md docs/V2/README.md
git commit -m "docs(v2): GA cutover train notes and gate checklist (ZCP-N)"
# design repo separately:
# git commit -m "docs(zcm): mark V2 beta spine done pending 2.0.0 cutover"
```

---

### Task 2: Production profile hard rejects (SECURITY §23)

**Objective:** `profile=production` fails closed on `auth_mode=none` and TLS verify disabled.

**Files:**

- Modify: `src_v2/zeus_client/config/profiles.py` and/or `config/loader.py` / `config/models.py`  
- Create/Modify: `tests/unit/config/test_production_profile_security.py` (path may match existing unit layout)

**Step 1: Failing tests**

```python
import pytest
from zeus_client_v2.config.models import RuntimeConfig, ZeusEndpoint  # adjust imports to real models
from zeus_client_v2.config.profiles import apply_profile
from zeus_client_v2.domain.errors import ZeusClientError, ErrorCode

def test_production_rejects_auth_mode_none():
    base = RuntimeConfig(...)  # minimal valid with zeus.auth_mode="none"
    with pytest.raises(ZeusClientError) as ei:
        apply_profile(base, "production")  # or validate_runtime_config after profile
    assert ei.value.code in {ErrorCode.CONFIG_INVALID, ErrorCode.CLIENT_CONFIG_INVALID}  # use real code

def test_production_rejects_tls_verify_off():
    ...
```

**Step 2:** `pytest tests/unit/config/test_production_profile_security.py -v` → FAIL.

**Step 3: Implement**

- After `apply_profile(..., "production")` or in `load_runtime_config` when profile is production:  
  - if `zeus.auth_mode == "none"` → raise typed config error (safe public message).  
  - if TLS verify explicitly false (field name as in `ZeusEndpoint` / httpx config) → raise.  
- `development` / `ci` may still allow `none` for lab.  
- Document in `docs/V2/SECURITY.md` §23 checklist → ✅.

**Step 4:** tests PASS; full `pytest -q` still green.

**Commit:** `feat(v2): production profile rejects auth_mode=none and tls verify off (ZCP-N)`

---

### Task 3: Alias cleanup + public surface freeze tests

**Objective:** ZCM-032 remove deprecated typeahead aliases from any tree that will ship; lock `__all__` / smoke imports for GA public API.

**Files:**

- Modify: `src/zeus/suggest.py`, `src/__init__.py`, `tests/test_smoke_imports.py`, `tests/test_zeus_suggest.py`, `docs/FAST_SUGGEST.md`  
- Modify: `src_v2/zeus_client/__init__.py` only if any alias leaked  
- Create: `tests/unit/test_public_api_exports.py` (import freeze)

**Steps:**

1. Delete `run_fast_suggest` / `run_fast_suggest_from_config` aliases and tests that assert identity.  
2. Update docs: “removed in 2.0; use `run_search` / `rt.data.search`”.  
3. Add freeze test listing expected public names from IG Phase 8 checklist (`ZeusRuntime`, models, peel helpers, hash helpers — **not** `application.*`).  
4. Ensure `py.typed` will ship with default package (package-data after flip).

**Commit:** `refactor(v2): remove run_fast_suggest aliases; freeze public exports (ZCP-N)`

---

### Task 4: demo_yelp → native V2 BFF (cutover blocker)

**Objective:** Clear MIGRATION “keep yelp on 0.3.1 until cutover” by migrating the last large monorepo path consumer **before** default-import flip.

**Workspace:** `/home/michael/koten-ai/demo_yelp` (branch `feat/ZD-…-v2-bff` or similar).  
**Pattern:** Travel + sample BFF — `runtime_factory`, lifespan cache, `rt.agent.run_turn`, `rt.data.search` / `rt.data.find`, health → V2 version.  
**SoT:** skill **zeus-demo-app** `references/travel-v2-bff.md` + package `docs/V2/MIGRATION.md` demo notes.  
**Jira:** prefer **ZD** epic for yelp; link as blocker on ZCP cutover epic.

**Minimum module map (create/adapt):**

| Path | Role |
| --- | --- |
| `src/local_guide/runtime_factory.py` | Wire `HttpxZeusPort` + LLM + `FsCatalogStore` + secrets |
| `src/local_guide/runtime_lifecycle.py` | Cache + aclose |
| `src/local_guide/search.py` (or equiv) | `run_turn` + TurnResult → existing JSON contract |
| `src/local_guide/suggest.py` | `rt.data.search` not `run_agent` |
| detail/reviews | `rt.data.find` (+ existing N1QL hydrate app-side) |
| health route | `zeus_client_version` from **import used by BFF** |

**Hard rules for yelp:**

- No final `compat.v1`.  
- No `application.*`.  
- Preserve SPA contracts (`/api/search`, `/api/suggest`, business detail/reviews, session isolation).  
- AST/no-V1 guard in demo tests.  
- `pytest -q` in demo_yelp green.

**Commit (demo repo):** `feat(v2): migrate LocalAI BFF to ZeusRuntime (ZD-N)`  
**Package ticket:** comment “blocker cleared” with demo SHA + pytest count — do not merge cutover without this.

**Parallel option (only if yelp blocked on product):** cutover may ship with **documented** “yelp remains on release pin 0.3.1 wheel” for one sprint — **not preferred**; call out as open question §8.

---

### Task 5: Default-import flip + version 2.0.0 (the cutover)

**Objective:** Make `import zeus_client` load the V2 tree; set all version clocks to **2.0.0**.

**Files:**

- Modify: `pyproject.toml` (`version`, `package-dir`, `packages`, `package-data`)  
- Move/rename: `src_v2/zeus_client/` → `src/zeus_client/` (or swap package-dir mapping carefully)  
- Archive: old flat `src/*.py` V1 tree → `src_v1_legacy/` (not in packages) **or** delete after Task 4 green  
- Modify: `_version.py` / version constants → `2.0.0`  
- Modify: every internal import still saying `zeus_client_v2` → `zeus_client` **inside the V2 tree**  
- Modify: tests that `import zeus_client_v2` → `import zeus_client` (keep a thin deprecation test for alias if Task 6 adds it)  
- Modify: `sdk_bootstrap.pins.json` `last_reviewed`; keep `claim_level=candidate`  
- Modify: `docs/V2/*` dual-tree language → historical + cutover complete pending MATRIX

**Recommended mechanical sequence:**

```bash
# 1) Ensure working tree clean except intentional changes
# 2) Move V1 aside
mkdir -p src_v1_legacy
# move old flat modules into src_v1_legacy/ (agent, zeus, …) — exact paths per tree

# 3) Promote V2 tree
# Option A (clean):
rm -rf src/zeus_client 2>/dev/null
mkdir -p src
git mv src_v2/zeus_client src/zeus_client
# rewrite package name inside from zeus_client_v2 → zeus_client (codemod)

# 4) pyproject.toml
# package-dir = {"zeus_client" = "src/zeus_client"}  # or {"zeus_client"="src/zeus_client"} matching layout
# packages = [explicit zeus_client.* list only]
# version = "2.0.0"
# package-data zeus_client = ["py.typed", "data/**/*" if any]
```

**Codemod rules:**

- `zeus_client_v2` → `zeus_client` in promoted tree and V2 tests.  
- Do **not** rewrite demo repos in the same commit as package codemod (yelp already native).  
- Keep `compat.v1` import path as `zeus_client.compat.v1`.

**Version assertions:**

```bash
pip install -e ".[dev]" --force-reinstall
python -c "import zeus_client; print(zeus_client.__version__); from zeus_client import ZeusRuntime"
# expect 2.0.0 and ZeusRuntime
pytest -q
```

**Fail closed:** if any test still expects tuple `run_agent` as default public API without compat path — move to `tests/compat/` or delete as V1 oracle.

**Commit:** `feat(v2): default import ZeusRuntime tree; release 2.0.0 cutover (ZCP-N)`

---

### Task 6: Temporary `zeus_client_v2` alias + V1 archive policy

**Objective:** One-minor bridge for BFFs that already import `zeus_client_v2` (Travel, sample).

**Files:**

- Create: thin package `zeus_client_v2` that re-exports `zeus_client` with `DeprecationWarning` on import **or** setuptools extra mapping  
- Modify: `tests/unit/test_zeus_client_v2_alias.py`  
- Docs: removal target **2.1.0** (or next minor)

**Implementation sketch:**

```python
# src/zeus_client_v2_alias/__init__.py  (installed as zeus_client_v2)
import warnings
warnings.warn(
    "zeus_client_v2 is deprecated; import zeus_client (2.0+). "
    "Alias removes on or before 2.1.0.",
    DeprecationWarning,
    stacklevel=2,
)
from zeus_client import *  # noqa: F403
from zeus_client import __version__, __all__  # ensure
```

**V1 archive:**

- If `src_v1_legacy/` kept: README note “not installed; historical oracles only”.  
- Prefer **not** shipping V1 modules on PyPI 2.0.0.  
- Compat free functions live only under `zeus_client.compat.v1`.

**Commit:** `feat(v2): deprecate zeus_client_v2 alias; archive V1 tree off install path (ZCP-N)`

---

### Task 7: Examples, README, CHANGELOG, MIGRATION final pass

**Objective:** Integrators landing on 2.0.0 see Runtime-first docs; dual-tree instructions become historical.

**Files:**

- Modify: `examples/minimal_agent.py`, `examples/run_search.py`, `examples/fast_suggest.py` → `rt.*`  
- Modify: root `README.md` (install, quickstart, version badge)  
- Create/Modify: `CHANGELOG.md` entry **2.0.0** breaking changes (from MIGRATION breaking list)  
- Modify: `docs/V2/MIGRATION.md` — cutover gate items 1–5 checked; item 6 “human MATRIX pending”  
- Modify: `docs/V2/SECURITY.md` §23 checkboxes  
- Modify: `docs/V2/IMPLEMENTATION_GUIDE.md` Phase 8 milestones checkboxes  
- Modify: skill `references/v2-train.md` progress table (after land)

**Breaking changes to list explicitly:**

- No tuple public returns on native API.  
- No process-global HTTP.  
- No public `run_pipeline`.  
- Catalog never silent sibling `*__*` rglob.  
- Default import is Runtime tree; free-function API only via `compat.v1` (deprecated).  
- `run_fast_suggest*` removed.  
- Production profile rejects `auth_mode=none`.

**Commit:** `docs(v2): 2.0.0 GA docs, examples, changelog (ZCP-N)`

---

### Task 8: Verification DoD (package + consumers)

**Objective:** Prove GA definition-of-done before tag.

**Commands (package):**

```bash
cd /home/michael/koten-ai/zeus_client_python
pytest -q
# optional:
# python -m mypy -p zeus_client --ignore-missing-imports  # if configured
python -c "import zeus_client; assert zeus_client.__version__=='2.0.0'"
# conformance offline (existing adapter path)
pytest tests/conformance -q
```

**Consumers:**

```bash
# demo_yelp
cd /home/michael/koten-ai/demo_yelp && pytest -q
curl -sS localhost:5000/api/health | jq .zeus_client_version   # expect 2.0.0 when live

# Travel V2 worktree if present
# sample app worktree:
cd /home/michael/koten-ai/zeus_client/.worktrees/v2-client-python && pytest -q
# fix imports if still hard-coded zeus_client_v2 without alias
```

**DoD checklist (IG § Definition of done + MIGRATION gate):**

- [ ] `TurnResult.debug` answers operator questions for multi-hop lab turn  
- [ ] Session-trace aggregate still green (ported tests)  
- [ ] Typeahead + verbs never call agent use-case  
- [ ] No secrets in prod-profile journal export tests  
- [ ] Transport replay greentests pass  
- [ ] Full pytest green; version aligned `pyproject` == `__version__` == **2.0.0**  
- [ ] Migration validated on ≥1 demo (yelp **and** prior Travel/sample)  
- [ ] SECURITY §23: prod auth_mode=none ✅; pip audit ticketed if still deferred  
- [ ] Wishlist Pri-1 done notes (design PR)  
- [ ] `compat.v1` warns; removal dated ≤1 minor  
- [ ] pins `claim_level` still **candidate** until Task 9 human MATRIX  

**Commit:** `test(v2): GA cutover verification notes (ZCP-N)` only if test fixes needed; else ticket comment only.

---

### Task 9: Tag 2.0.0 + design MATRIX handoff (human gate)

**Objective:** Publish tag; do **not** auto-flip MATRIX.

**Steps:**

1. Merge `feat/ZCP-ga-cutover-2.0.0` → `feat/V2` / `main` per team branch policy (prefer PR review).  
2. Tag:

```bash
git tag -a v2.0.0 -m "kotenai-zeus-client 2.0.0 — journaled hexagonal runtime GA"
# push tag only after human approve
```

3. **Design repo (human):** open PR on `MATRIX.md` / CHECKLIST — `candidate` → `supported` **only** if suite policy and reviewers agree. Agent must not self-award.  
4. Update pins in a **follow-up** commit only after MATRIX merges: `claim_level=supported`.  
5. PyPI publish (human/CI secret) — out of band if not automated.  
6. Close ZCP cutover epic; comment final SHA + pytest + consumer SHAs.

**Post-GA (explicitly next train — not this plan):**

- Remove `zeus_client_v2` alias (≤1 minor).  
- Remove `compat.v1` if usage low.  
- ZCM-030/031 hydrate timeouts, 041–043 export CLI, 044+ streaming/turn-diff.

---

## 5. Files likely to change (train-wide)

### Package

```text
pyproject.toml
sdk_bootstrap.pins.json
src/                          # layout surgery
src_v2/                       # removed after promote
src_v1_legacy/                # optional archive
src/zeus_client/_version.py
src/zeus_client/__init__.py
src/zeus_client/config/profiles.py
src/zeus_client/config/loader.py
src/zeus_client/compat/v1/*
tests/**                      # import rewrites + new security/export freeze tests
examples/*
docs/V2/MIGRATION.md
docs/V2/README.md
docs/V2/SECURITY.md
docs/V2/IMPLEMENTATION_GUIDE.md
docs/FAST_SUGGEST.md
README.md
CHANGELOG.md
```

### Consumers (separate repos/PRs)

```text
demo_yelp/src/local_guide/*   # runtime_factory, search, suggest, health
demo_travel_sample/...        # retest / optional drop _v2 import
zeus_client sample worktree   # retest / optional drop _v2 import
```

### Design (separate PR)

```text
MICHAEL_WISHLIST.md           # status done + version
MATRIX.md / CHECKLIST.md      # human supported flip
docs/MICHAEL/09-*.md          # optional checkbox sync
```

---

## 6. Risks / tradeoffs

| Risk | Mitigation |
| --- | --- |
| Monorepo yelp breaks on import flip | **Task 4 before Task 5**; health assert 2.0.0 |
| Travel/sample hard-code `zeus_client_v2` | Task 6 deprecation alias ≤1 minor |
| Codemod misses nested `zeus_client_v2` imports | `rg zeus_client_v2` gate in Task 5/8 |
| Coverage cliff deleting V1 oracles | Keep behavioral tests under V2 paths; archive V1 tests only if duplicated |
| Accidental MATRIX self-award | Task 9 human-only; pins stay candidate |
| Prod reject `auth_mode=none` breaks lab configs | Only `production` profile; dev/ci unchanged |
| Dual PR chaos (package + yelp + design) | Package cutover blocked on yelp green SHA; design wishlist can land earlier |
| Tag before consumer smoke | Task 8 checklist mandatory |
| Scope creep (streaming, CEL, hydrate server) | Explicit post-GA; YAGNI |

---

## 7. Out of scope

- Re-implementing journal/hex spine (ZCP-2…22)  
- Hub HTML Detective clone  
- Public Direct pipeline  
- Multi-agent / plugins  
- Forging stamps  
- Self-awarding MATRIX `supported`  
- Post-GA ZCM-044–067 product features  
- Rewriting chat-trace widget  
- Changing Zeus engine or BASE `CURRENT.json`  
- Sample-app feature work beyond import retest  

---

## 8. Open questions (resolve at execute if blocking)

1. **demo_yelp sequencing** — migrate fully before cutover (**default**) vs pin yelp on 0.3.1 release wheel for one sprint?  
2. **V1 source retention** — `src_v1_legacy/` uninstalled archive vs delete immediately after yelp green? Default: **archive one minor**, delete in 2.1.  
3. **`zeus_client_v2` alias** — setuptools extra package vs warn-only re-export module? Default: **warn re-export**.  
4. **Branch integration** — cutover merges to `feat/V2` then main, or direct main PR? Default: **PR into feat/V2**, then release PR to main + tag.  
5. **`pip audit` in CI** — implement non-blocking now or ticket-only for GA? Default: **ticket + BEST_PRACTICES note**; blocking audit = 2.0.1 ops.  
6. **Jira epic number** — **resolved:** epic **ZCP-33**; stories **ZCP-34…43**; yelp **ZD-20**; pip-audit **ZCP-44**.

---

## 9. Execution handoff

Plan complete and saved at:

`zeus_client_python/.hermes/plans/2026-08-13_040155-zeus-client-python-v2-ga-cutover.md`

**Primary SoT reminders for implementers:**

1. Package `docs/V2/MIGRATION.md` §Cutover gate  
2. Design `docs/MICHAEL/09-ship-bands-and-verification.md` §9.5  
3. SECURITY.md §23  
4. Travel + sample BFF patterns (native `rt.*` only)  
5. This plan’s hard rules + **yelp before package-dir flip**

**Suggested execute order:** T0 → T1/T2/T3 parallel → **T4 yelp** → T5 cutover → T6 alias → T7 docs → T8 verify → T9 human tag/MATRIX.

Ready to execute using **subagent-driven-development** — fresh subagent per task with two-stage review (spec compliance then code quality). Shall I proceed?
