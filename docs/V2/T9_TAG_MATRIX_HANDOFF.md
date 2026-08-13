# T9 — Tag `v2.0.0` + MATRIX handoff checklist (human gate)

> **Ticket:** [ZCP-43](https://kotenai.atlassian.net/browse/ZCP-43) · Epic [ZCP-33](https://kotenai.atlassian.net/browse/ZCP-33)  
> **Train plan:** `.hermes/plans/2026-08-13_040155-zeus-client-python-v2-ga-cutover.md`  
> **Law:** design `CANDIDATE_CHARTER.md` STOP C · package `MIGRATION.md` cutover gate #6  
> **Owner:** human reviewer (agents **must not** self-award `supported` or invent COMPAT triples)

---

## 0. What T9 is (and is not)

| T9 **is** | T9 **is not** |
| --- | --- |
| Annotated git tag **`v2.0.0`** on package `main` | Re-running cutover surgery (T0–T8 already Done) |
| GitHub Release via `.github/workflows/release.yml` | Automatic PyPI (publish step still commented) |
| Design-repo **MATRIX / CHECKLIST** honesty PR | Agent flipping `claim_level` unattended |
| Optional pins follow-up **after** MATRIX merges | Forging chat_request COMPAT rows |
| Close ZCP-33 / ZCP-43 with evidence | Claiming multi-agent, plugins, or “v2 complete” family bar |

**Claim ladder (charter):** package may ship **2.0.0** while pins stay **`candidate`**.  
`supported` is a **separate** human decision after suite + MATRIX (+ usually COMPAT).

```text
[package 2.0.0 on main]  →  tag v2.0.0 + GH Release
                              ↓
                    design MATRIX PR (human)
                              ↓
              only if approved: pins claim_level=supported
                              ↓
                    optional PyPI / COMPAT row
```

---

## 1. Preconditions (verify before tag) — ~10 min

Work from a clean clone of **package** `main` (not stale `feat/V2`).

```bash
cd /home/michael/koten-ai/zeus_client_python
git fetch origin
git checkout main
git pull --ff-only origin main
git status   # clean
```

### 1.1 Version clocks (must match tag body)

| Clock | Expected |
| --- | --- |
| `pyproject.toml` `version` | `2.0.0` |
| `src/zeus_client/_version.py` `__version__` | `2.0.0` |
| `import zeus_client; zeus_client.__version__` | `2.0.0` |
| Default public type | `zeus_client.ZeusRuntime` |
| `import zeus_client_v2` | same version + `DeprecationWarning` |
| `sdk_bootstrap.pins.json` → `claim.claim_level` | **`candidate`** until §5 |

```bash
python -c "import zeus_client; from zeus_client import ZeusRuntime; print(zeus_client.__version__, ZeusRuntime)"
# expect: 2.0.0 <class 'zeus_client.runtime.ZeusRuntime'>
rg -n '^version\s*=' pyproject.toml
rg -n '__version__' src/zeus_client/_version.py
python -c "import json; print(json.load(open('sdk_bootstrap.pins.json'))['claim']['claim_level'])"
# expect: candidate
```

### 1.2 Offline green (local or trust latest CI on `main`)

```bash
. .venv/bin/activate   # or: python3 -m venv .venv && pip install -e ".[dev]"
pytest -q -m "not integration"
# Fresh T0 re-audit (2026-08-13): 239 passed on main@65a38db
```

Optional consumers (already dogfood’d):

| Consumer | Board / tip (at T8) | Expect |
| --- | --- | --- |
| demo_yelp | ZD-20 `844f61b` | pytest **78** (may warn on `zeus_client_v2` alias) |
| sample try-Zeus | ZC-56 closed `f6aeead` / worktree | pytest **245** |
| Travel | ZD-8 | V2 BFF landed |

### 1.3 Docs already on main (no rewrite required for tag)

- [ ] `CHANGELOG.md` has `## 2.0.0` section (release workflow scrapes it)
- [ ] `docs/V2/MIGRATION.md` cutover gate 1–5 **Met**; #6 Open until MATRIX
- [ ] README banner: **2.0.0** + claim **candidate**
- [ ] No accidental `claim_level: supported` in pins before MATRIX

### 1.4 Tag must not already exist

```bash
git tag -l 'v2.0.0'
# empty → proceed; if present, stop and verify it points at intended SHA
```

**Baseline SHA note (T0 re-audit):** `main` included cutover PR **#10** + CI PR **#11** @ `65a38db`.  
Re-resolve tip at tag time — do not hard-code that SHA into the tag message if main moved.

---

## 2. Phase A — Git tag + GitHub Release (package repo)

### 2.1 Create annotated tag (human)

```bash
# On main tip after §1 green:
git tag -a v2.0.0 -m "kotenai-zeus-client 2.0.0 — journaled hexagonal runtime GA (claim: candidate until MATRIX)"

# Inspect:
git show v2.0.0 --no-patch
git rev-parse v2.0.0^{}
```

### 2.2 Push tag (triggers Release workflow)

```bash
git push origin v2.0.0
```

Workflow: `.github/workflows/release.yml`  
On `push: tags: ["v*"]` it will:

1. Align tag semver ↔ `pyproject` ↔ `_version.py` (fail if mismatch)
2. `pytest -q -m "not integration"` with coverage floor
3. `python -m build` + `twine check`
4. Create **GitHub Release** `v2.0.0` with CHANGELOG body + `dist/*` artifacts

**Fallback:** Actions → Release → Run workflow → input `v2.0.0` (workflow_dispatch).

### 2.3 Verify Release job

- [ ] Workflow **green**
- [ ] GitHub Release **v2.0.0** exists with wheel + sdist
- [ ] Release notes include breaking list from CHANGELOG (Runtime default, no tuples, no public pipeline, prod rejects `auth_mode=none`, …)
- [ ] PyPI step still **disabled** unless you intentionally enable Trusted Publishing (§6)

### 2.4 Jira comment (ZCP-43) after green Release

Paste:

```markdown
T9 Phase A — tag pushed
- tag: v2.0.0 → <FULL_SHA>
- main tip at tag: <SHORT_SHA>
- Release workflow: <URL> green
- package pytest: <N> passed (CI)
- claim_level: still **candidate** (pins unchanged)
- next: design MATRIX PR (Phase B) — no pins flip yet
```

---

## 3. Phase B — Design MATRIX handoff (separate repo / PR)

**Repo:** `zeus_client_design`  
**Files (minimum):** `MATRIX.md`, optionally `CHECKLIST.md`, `MICHAEL_WISHLIST.md` residual honesty, book §9 if checkboxes lag  
**Do not:** edit COMPAT.md in chat_request from this PR unless product explicitly opens a COMPAT train

### 3.1 Decision fork (human chooses one)

| Path | When | MATRIX Status cell | pins after merge |
| --- | --- | --- | --- |
| **B1 — Honest refresh, stay candidate** | Suite/COMPAT not ready for production “supported” | `candidate` | leave `candidate` |
| **B2 — Award supported** | Required suite green + reviewer OK + COMPAT path clear or ticketed | `supported` | then §5 pins follow-up |

Charter default if unsure: **B1**. Shipping the tag does **not** force B2.

### 3.2 `MATRIX.md` §2 Language status — proposed Python row

**Today (stale scaffold):** version `0.1.x`, suite *none*, status **partial**.

**Suggested after 2.0.0 package GA (B1 candidate):**

| Field | Proposed value |
| --- | --- |
| Version | `2.0.0` |
| Floor claimed | `client-floor-5` (matches pins; residual floor-6.x optional note) |
| BASE packs claimed | offline mock `base-5-mock` + lab stamped scopes; **not** a forged COMPAT triple |
| Suite | `conformance-0.2-dev` offline required (L0–L2) — record suite id honestly |
| multi_agent | **no** |
| semantic_cache | **docs** (v2 ship bar residual — not runtime **supported**) |
| Status | **candidate** (B1) or **supported** (B2 only) |

Update doc header “last reviewed” date.

### 3.3 `MATRIX.md` §3 Capability × language — Python column (honest floor)

Prefer suite-backed **yes** over README optimism. Starting point for human edit (adjust if suite disagrees):

| Capability | Suggested Python (2.0.0) | Notes |
| --- | --- | --- |
| Load stamped catalog / lineage | **yes** / **partial** | fail-closed path; live stamp still Hub SoT |
| `catalog.mini_schema.get` | **partial** | parse/helpers; live not always first-class |
| Multi-round messages[] + bags | **yes** / **partial** | agent turn path |
| Zeus V2 tool dispatch + return | **yes** | Direct + agent tools; **no** public `pipeline` |
| Named rules{} merge/freeze | **yes** / **partial** | control-plane inject |
| Object business_rules_triggers | **partial** / **yes** | if suite covers |
| Settings bag | **yes** | `ClientSettings` / RuntimeConfig |
| output_request → app_output | **yes** / **partial** | Layer A path |
| Post-terminate policy table | **yes** / **partial** | domain policy |
| Required four Layer A | **yes** | peel + quarantine |
| G1/G2/G3 redaction | **partial** / **yes** | journal/export redactor; family LOGGING depth may lag |
| AgentHooks + dual jailbreak scores | **partial** / **yes** | middleware / policy |
| Durable sessions | **yes** | session lifecycle + session-trace projector |
| Stamp `user` + `ip_address` | **partial** | pins `user=zeus_client`; ip product residual |
| `ai_process_result` default false | **no** (honest) | **package default True (Hub)**; pins document product-cheap false |
| `ignore_user_tool_path_hints` | **docs** / **partial** | family ZCF — don’t over-claim |
| Conformance suite adapter | **yes** (offline) | ZCP-21; suite version in pins |
| OTel logs + REDACT + 4 levels | **partial** | optional OTLP stub; not full family LOGGING bar |
| Multi-agent ready | **no** | |
| Semantic agent cache | **docs** | |

### 3.4 `MATRIX.md` §5 Conformance suite versions

| Suite | Gates | Languages green |
| --- | --- | --- |
| `conformance-0.2-dev` | L0–L2 required per pins | **Python** (offline candidate) — fill only if still green on tag SHA |

If suite id/name differs in design repo, **use design SoT**, not this draft.

### 3.5 `CHECKLIST.md` / `MICHAEL_WISHLIST.md`

- [ ] CHECKLIST: no box implies `supported` without suite note  
- [ ] Pri-1 ZCM-001…012: status **done** + Python **2.0.0** where code truly shipped (catalogue still lags some **partial** rows — fix or leave with reason)  
- [ ] Do **not** mark post-GA ZCM-044+ done  
- [ ] semantic_cache / multi_agent remain non-supported unless deliberately in scope  

### 3.6 Design PR body template

```markdown
## MATRIX honesty for kotenai-zeus-client 2.0.0

Package: https://github.com/koten-ai/zeus_client_python @ v2.0.0 (<sha>)
Epic: ZCP-33 · handoff: ZCP-43
Claim path: B1 candidate | B2 supported  (pick one)

### Evidence
- GH Release: <url>
- Offline pytest: <n> passed
- Conformance: <command + result>
- Dogfood BFFs: Travel ZD-8, sample ZC-56, yelp ZD-20

### Explicit non-claims
- multi_agent=no
- plugins=no
- semantic_cache ≠ supported
- no new COMPAT triple forged in this PR
- package ai_process_result default remains True (Hub)

### Follow-up
- [ ] pins claim_level only if B2 merges
- [ ] COMPAT row ticket (if B2): <link or TBD>
```

### 3.7 Reviewer gate questions

1. Is offline suite required set still green on the **tagged** SHA?  
2. Are we awarding **family** `supported` or only acknowledging package GA + **candidate**?  
3. Is chat_request **COMPAT** ready for a Python **2.0.0** triple, or ticketed?  
4. Does capability table avoid Hub Debug Chat as a product SDK column?  
5. Any demo still requiring uninstalled V1 free functions without `compat.v1`?

---

## 4. Phase C — Package pins follow-up (**only after B2 MATRIX merge**)

**If B1 (stay candidate): skip this phase.** Tag alone is enough for T9 Phase A closeout.

```bash
# On a short-lived branch from main:
# sdk_bootstrap.pins.json
#   claim.claim_level: "candidate" → "supported"
#   last_reviewed: <today>
#   blocked_without: drop or reword "For supported claim: suite green + COMPAT row" if satisfied
```

```bash
git commit -m "chore(pins): claim_level=supported after MATRIX (ZCP-43)"
# PR → main; do not sneak into the tag commit
```

Also update package README claim table if it still says candidate.

**Forbidden:** setting `supported` in the same commit as the tag without a merged MATRIX PR.

---

## 5. Phase D — Optional PyPI

`release.yml` PyPI step is **commented** until Trusted Publishing / token is configured.

- [ ] Enable `id-token: write` + `pypa/gh-action-pypi-publish` **or** manual `twine upload dist/*`  
- [ ] Confirm project name `kotenai-zeus-client` **2.0.0** on PyPI  
- [ ] Yank policy agreed if bad release  

Not required to close ZCP-43 if GH Release artifacts are the lab distribution channel.

---

## 6. Phase E — Close-out tickets & hygiene

| Action | Detail |
| --- | --- |
| ZCP-43 | Done (`41`) + comment: tag SHA, Release URL, MATRIX PR URL, pins yes/no |
| ZCP-33 epic | Done when T9 accepted; link consumers |
| ZD-20 / ZC-56 / ZD-8 | No package reopen; optional “imports still `_v2` alias” cleanup tickets |
| Stale local `feat/V2` | Delete or reset to `main` — dual-tree tip is historical |
| Plan / MIGRATION | Gate #6 → Met **only** after MATRIX path chosen (B1 note or B2 merge) |
| This doc | Check boxes in a copy or leave as runbook |

### Post-T9 backlog (not T9)

- Remove `zeus_client_v2` alias ≤ **2.1.0**  
- Remove `compat.v1` if usage low  
- demo_yelp: `zeus_client_v2` → `zeus_client` (silence warnings)  
- ZCM-030/031/041–043 polish; ZCM-044+ post-GA  
- `pip-audit` blocking CI — [ZCP-44](https://kotenai.atlassian.net/browse/ZCP-44)  
- COMPAT triple authoring (chat_request owners)

---

## 7. Copy-paste command block (Phase A only)

```bash
set -euo pipefail
cd /home/michael/koten-ai/zeus_client_python
git fetch origin && git checkout main && git pull --ff-only
test -z "$(git status --porcelain)" || { echo "dirty tree"; exit 1; }

python -c "import zeus_client; assert zeus_client.__version__=='2.0.0'"
python -c "import json; assert json.load(open('sdk_bootstrap.pins.json'))['claim']['claim_level']=='candidate'"
pytest -q -m "not integration"

git tag -l 'v2.0.0' | grep -q . && { echo "tag exists"; exit 1; }
git tag -a v2.0.0 -m "kotenai-zeus-client 2.0.0 — journaled hexagonal runtime GA (claim: candidate until MATRIX)"
git push origin v2.0.0
echo "Watch Actions → Release workflow; then open design MATRIX PR (Phase B)."
```

---

## 8. Evidence snapshot (filled at T0 re-audit — refresh at tag time)

| Item | 2026-08-13 re-audit |
| --- | --- |
| Package `main` | `65a38db` (cutover #10 + CI #11) |
| Package pytest | **239 passed** |
| yelp ZD-20 | **78 passed** @ `844f61b` |
| sample | **245 passed** |
| claim_level | **candidate** |
| Tag `v2.0.0` | **absent** |
| MATRIX Python row | still scaffold `0.1.x` / **partial** — **needs Phase B** |

---

## 9. Definition of done for ZCP-43

**Minimum (recommended ship):**

- [x] Cutover code on `main` (T0–T8)  
- [ ] Annotated **`v2.0.0`** pushed  
- [ ] Release workflow green + GH Release artifacts  
- [ ] Design PR opened (even if B1 candidate-only) updating stale Python MATRIX row to **2.0.0**  
- [ ] pins remain **candidate** unless B2 merges  
- [ ] ZCP-43 commented + transitioned  

**Full supported ladder (optional same sprint):**

- [ ] MATRIX Status = **supported** merged  
- [ ] pins `claim_level=supported` follow-up on package  
- [ ] COMPAT row or explicit deferred ticket  
- [ ] Optional PyPI  

---

*Agents: stop after drafting evidence and opening PRs if asked. Never set MATRIX/pins to `supported` without human instruction that names this ladder.*
