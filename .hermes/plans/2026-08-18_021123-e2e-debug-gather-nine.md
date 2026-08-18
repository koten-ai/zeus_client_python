# E2E debug gather (nine fields) Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Every agent `TurnResult.debug` (and a smaller data-plane bundle) carries the nine gather fields so an integrator can reconstruct a real end-to-end debug **without knowing Hub Detective**.

**Architecture:** The journal + hop records stay SoT. Project them onto a typed `DebugBundle` (ZCM-007). `trace.detective` / `support_pack` become **views** of that bundle — do not gather twice. Session-trace join stays **opt-in** (`enable_sessions=True`); do **not** auto-enable from `durable_sessions`. Hub URLs are optional links built from config, never scraped HTML.

**Tech Stack:** Python 3.11+ · `kotenai-zeus-client` 2.0.0 · pytest · existing hexagonal ports (`TurnResult`, `DebugBundle`, `SessionLifecycle`, `export_journal_redacted`)

### Jira map (created 2026-08-18)

Board: [ZCP](https://kotenai.atlassian.net/jira/software/projects/ZCP) · assignee **Michael Arcega** · status **To Do**. Blocks: 86→87→…→99.

| Plan task | Key | Summary |
| --- | --- | --- |
| Epic | [ZCP-85](https://kotenai.atlassian.net/browse/ZCP-85) | Client E2E debug gather (nine fields) |
| T1 | [ZCP-86](https://kotenai.atlassian.net/browse/ZCP-86) | feat(debug): extend DebugBundle with gather ids + target |
| T2 | [ZCP-87](https://kotenai.atlassian.net/browse/ZCP-87) | feat(agent): stamp chat/session/req_ids on every finish |
| T3 | [ZCP-88](https://kotenai.atlassian.net/browse/ZCP-88) | feat(agent): tools-from-verbs + catalog flags on bundle |
| T4 | [ZCP-89](https://kotenai.atlassian.net/browse/ZCP-89) | feat(detective): BRIEF/MINI slice sha12 (not whole system) |
| T5 | [ZCP-90](https://kotenai.atlassian.net/browse/ZCP-90) | feat(hops): url, error, 2000-char snippet, pipeline meta |
| T6 | [ZCP-91](https://kotenai.atlassian.net/browse/ZCP-91) | feat(layer-a): compact terminate bag on public_trace |
| T7 | [ZCP-92](https://kotenai.atlassian.net/browse/ZCP-92) | feat(debug): tokens + client version + zeus.url on bundle |
| T8 | [ZCP-93](https://kotenai.atlassian.net/browse/ZCP-93) | feat(debug): journal export_ref on TurnResult |
| T9 | [ZCP-94](https://kotenai.atlassian.net/browse/ZCP-94) | feat(detective): support_pack markdown includes all nine |
| T10 | [ZCP-95](https://kotenai.atlassian.net/browse/ZCP-95) | feat(session): wire SessionLifecycle into run_agent_turn |
| T11 | [ZCP-96](https://kotenai.atlassian.net/browse/ZCP-96) | feat(api): AgentAPI injects lifecycle + hub_base_url |
| T12 | [ZCP-97](https://kotenai.atlassian.net/browse/ZCP-97) | feat(trace): public_trace.session block |
| T13 | [ZCP-98](https://kotenai.atlassian.net/browse/ZCP-98) | feat(data): small DebugBundle on direct/typeahead |
| T14 | [ZCP-99](https://kotenai.atlassian.net/browse/ZCP-99) | docs + make ci |

Close-out: commit `ZCP-N` → comment SHA + pytest → Done (`41`). Do **not** reuse ZCP-23…84.

---

## Current context / assumptions

Audit (this session) against `feat/ZCP-76-rewind-headers` @ `6b0b221`:

| # | Field | Today |
| --- | --- | --- |
| 1 | `chat_id` / `turn_id` / `session_id` | `turn_id` only on bundle; `chat_id` header-only; `session_id` only if caller passed a handle |
| 2 | `req_ids[]` + preferred + hop class | `preferred_req_id` yes; `req_ids` only inside `detective.overview`; hops lack path/url |
| 3 | Target + `zeus.url` + client version | Overview target yes; **no** url/version on result (version is HTTP stamp only) |
| 4 | Catalog flags + tools/verbs + contract | Prompt checklist if Detective on; `_tools_from_request` ignores CR `verbs`; contract only on passed session |
| 5 | Inject proof | Presence yes; sha hashes **whole** system |
| 6 | Hop table | `req_id/name/status/ok/ms/snippet[:500]` — no url/error/step_costs |
| 7 | Layer A + peeled answer | Peel yes; `public_trace.layer_a` thinned (no QD/decomp/synthetic) |
| 8 | Token rollup | **Present** on `public_trace.tokens` |
| 9 | Redacted journal export | `rt.debug.export_journal` exists; **not** referenced from `TurnResult` |

Also true:

- `SessionLifecycle` + `project_session_trace` exist but **`run_agent_turn` never calls them**. Untracked oracle: `tests/unit/application/test_agent_turn_session_join.py`.
- `AgentAPI.run_turn` hard-codes `hub_base_url=None`. `Services` has no `session_lifecycle`. `DebugPolicy` has no hub URL.
- `VerbHopResult` has no `url`.
- Rewind headers (ZCP-76…83) already stamp chat/turn/class on hops — keep that; this train **gathers** those ids onto the result.

**Workspace:** implement on a **new branch** off the Rewind tip (or main after merge): `feat/ZCP-NN-e2e-debug-gather`. Do not scoop Rewind WIP or untracked plans into the first commit.

---

## Non-goals (YAGNI)

- Do **not** clone Hub Detective HTML / Ask-Detective / storage FTS / live `scope_brief` fetch on the default path.
- Do **not** auto-enable sessions from `ClientSettings.durable_sessions=True`.
- Do **not** put full system prompt twice on the HTTP body (sha12 + ≤400 preview only).
- Do **not** put G2 (`wish_i_knew`, jail scores) on `answer` or compact `layer_a`.
- Do **not** pre-mint / reuse `X-Zeus-Req-Id`.
- Do **not** invent `contract_hash`.
- Do **not** require Hub to be up for the nine fields to appear.
- Do **not** change Zeus pipeline `[redacted]`.

---

## Target shape (locked)

```python
# DebugBundle — additive fields; keep existing ones
@dataclass(frozen=True, slots=True)
class DebugBundle:
    turn_id: str = ""
    chat_id: str | None = None
    session_id: str | None = None
    notes: tuple[str, ...] = ()
    rounds: int = 0
    ai_process_result: bool = True
    ai_process_result_exit: str | None = None
    public_trace: Mapping[str, Any] = field(default_factory=dict)
    hops: tuple[Mapping[str, Any], ...] = ()
    journal_event_count: int = 0
    hooks_jailbreak_score: float = 0.0
    detective: Mapping[str, Any] | None = None
    preferred_req_id: str | None = None
    req_ids: tuple[str, ...] = ()
    zeus_url: str | None = None
    client_version: str = ""          # zeus_client.__version__
    target: Mapping[str, Any] = field(default_factory=dict)
    catalog: Mapping[str, Any] = field(default_factory=dict)
    contract_status: str | None = None
    tokens: Mapping[str, Any] | None = None
    export_ref: str | None = None     # == turn_id; load via rt.debug.export_journal
    journal_schema: int = 1
```

Hop record (agent + session-trace normalize):

```python
{
  "req_id": "...",
  "name": "find|pipeline|search|...",
  "path_class": "find|pipeline|search|session_turn|other",
  "status": 200,
  "ok": True,
  "ms": 12,
  "url": "http://127.0.0.1:8080/v2/.../find",
  "error": None,                 # verbatim tool/transport error
  "snippet": "...",              # max TRACE_SNIPPET_MAX (2000)
  "step_costs": [...],           # if pipeline meta present
  "result_size": 0,
  "pipeline_status": None,
}
```

Compact `public_trace.layer_a` (no G2):

```python
{
  "ok": True,
  "summary": "...",
  "confidence": "high",
  "policy_action": "answer",
  "query_decomposition": {...},
  "decomposition": {...},
  "synthetic": False,
  "via": "client_terminate",     # or "pipeline_turn_complete"
}
```

`support_pack.markdown` **must** include all nine sections (see T9).

---

## Step-by-step plan

### Task 1: Extend `DebugBundle` (typed gather fields)

**Objective:** Additive frozen fields + `to_dict()` so later wiring has a stable surface.

**Files:**
- Modify: `src/zeus_client/domain/messages.py` (`DebugBundle`)
- Test: `tests/unit/domain/test_debug_bundle.py` (create)

**Step 1: Write failing test**

```python
from zeus_client.domain.messages import DebugBundle

def test_debug_bundle_to_dict_includes_nine_gather_keys() -> None:
    b = DebugBundle(
        turn_id="turn_abc",
        chat_id="chat_1",
        session_id="sess_1",
        preferred_req_id="req-a",
        req_ids=("req-a", "req-b"),
        zeus_url="http://127.0.0.1:8080",
        client_version="2.0.0",
        target={"bucket": "yelp-data", "scope": "_default", "collection": "_default", "mode": "analytics"},
        catalog={"has_scope_brief": True, "has_mini_schema": True, "tools_count": 13},
        contract_status="match",
        tokens={"prompt": 10, "completion": 4, "total": 14, "cached": 0, "extra": 0, "ok": True},
        export_ref="turn_abc",
    )
    d = b.to_dict()
    assert d["turn_id"] == "turn_abc"
    assert d["chat_id"] == "chat_1"
    assert d["session_id"] == "sess_1"
    assert d["req_ids"] == ["req-a", "req-b"]
    assert d["preferred_req_id"] == "req-a"
    assert d["zeus_url"].endswith(":8080")
    assert d["client_version"]
    assert d["target"]["bucket"] == "yelp-data"
    assert d["catalog"]["tools_count"] == 13
    assert d["contract_status"] == "match"
    assert d["tokens"]["ok"] is True
    assert d["export_ref"] == "turn_abc"
    assert "answer" not in d  # G2 / chat stay off the bundle
```

**Step 2:** `pytest tests/unit/domain/test_debug_bundle.py -q` — FAIL (`to_dict` missing).

**Step 3:** Add fields (defaults so existing `DebugBundle(...)` call sites still typecheck). Implement `to_dict()` returning only JSON-safe primitives. Do **not** embed `detective` twice if `public_trace` already has it — include `detective` key only at top level.

**Step 4:** Test PASS. Fix any construct-site type errors (`mypy` on `messages.py`).

**Step 5:** Commit `feat(debug): extend DebugBundle gather fields (ZCP-N)`

---

### Task 2: Stamp ids on every `_finish`

**Objective:** `chat_id`, `session_id`, `req_ids[]`, `preferred_req_id` always on the bundle, including error turns.

**Files:**
- Modify: `src/zeus_client/application/agent_turn.py` (`_finish`, `run_agent_turn`)
- Test: `tests/unit/application/test_agent_turn.py` (extend) or `tests/unit/application/test_debug_gather.py` (create)

**Step 1: Failing test** — scripted LLM no-tools turn with `chat_id="chat_x"` and no session:

```python
async def test_finish_stamps_chat_and_req_ids_on_errorless_direct_exit() -> None:
    # ... ScriptedLlm content-only ...
    result = await run_agent_turn(
        TurnRequest(message="hi", chat_id="chat_x"),
        llm=llm, zeus=None,
    )
    assert result.debug.turn_id.startswith("turn_")
    assert result.debug.chat_id == "chat_x"
    assert result.debug.session_id is None
    assert result.debug.req_ids == ()
    assert result.debug.preferred_req_id is None
```

Second test: one `find` hop `req_id="req-find"` → `req_ids == ("req-find",)` and `preferred_req_id == "req-find"`.

**Step 2:** FAIL — fields empty/missing.

**Step 3:** In `_finish`:

```python
from zeus_client.application.detective.extract import collect_req_ids
# ...
req_ids = collect_req_ids(hops)
pref = select_primary_req_id(list(hops)) if hops else None
debug = DebugBundle(
    ...,
    chat_id=getattr(session, "chat_id", None) or chat_id_from_req,
    session_id=session.session_id if session and session.session_id else None,
    req_ids=req_ids,
    preferred_req_id=pref,
)
```

Thread `req.chat_id` into `_finish` (add kwarg `chat_id=`). On error early-returns, pass the same kwargs (already a single `_finish`).

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(agent): stamp chat/session/req_ids on DebugBundle (ZCP-N)`

---

### Task 3: Tools-from-verbs + catalog flags on the bundle

**Objective:** Checklist and `debug.catalog` count **verbs** when `tools` is empty (standardized CR).

**Files:**
- Modify: `src/zeus_client/application/agent_turn.py` (`_tools_from_request`)
- Modify: `src/zeus_client/application/detective/prompt_checklist.py` (tools **or** verbs)
- Modify: `src/zeus_client/application/agent_turn.py` `_finish` to set `debug.catalog`
- Test: `tests/unit/application/test_tools_from_request.py` (create if missing) + prompt checklist test

**Step 1: Failing tests**

```python
def test_tools_from_request_falls_back_to_chat_request_verbs() -> None:
    req = TurnRequest(
        message="x",
        chat_request={"verbs": [{"type": "function", "function": {"name": "find"}}]},
    )
    tools = _tools_from_request(req)
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "find"

def test_prompt_checklist_counts_verbs_when_tools_empty() -> None:
    cl = build_prompt_checklist(
        tools=(),
        catalog={"verbs": [{"function": {"name": "find"}}] * 13},
        system_prompt="## SCOPE BRIEF\n...\n## MINI-SCHEMA\n...",
    )
    assert "tools=13" in cl["summary"]
```

**Step 2:** FAIL — count 0.

**Step 3:** Prefer `req.tools` → CR `tools` → CR `verbs`. **Never** copy verbs onto the CR body (hash). Prompt checklist: same fallback. `_finish.catalog`:

```python
{
  "has_scope_brief": flags["has_scope_brief"],
  "has_mini_schema": flags["has_mini_schema"],
  "tools_count": len(resolved_tools),
  "source": "tools" | "verbs" | "none",
}
```

Pass **resolved** tools into `safe_build_detective_briefing`, not the empty `req.tools`.

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(agent): resolve LLM tools from chat_request.verbs (ZCP-N)`

---

### Task 4: BRIEF / MINI slice sha12

**Objective:** Inject proof hashes only the marked slices, plus ≤400 previews.

**Files:**
- Modify: `src/zeus_client/application/detective/extract.py` (`catalog_flags_of`)
- Test: `tests/unit/application/test_detective.py` (extend)

**Step 1: Failing test** — system = preamble + `## SCOPE BRIEF\nAAA` + `## MINI-SCHEMA\nBBB`; assert `brief_sha12 == sha12("## SCOPE BRIEF\nAAA")` (or the slice body — pick one and lock it) **≠** `sha12(full_system)`.

**Step 2:** FAIL — currently `sha12(system)`.

**Step 3:** Parse with `(?ms)^##\s+SCOPE\s+BRIEF\b.*?(?=^##\s|\Z)` and same for MINI-SCHEMA. Keep `has_*` marker detection. Add `brief_preview` / `mini_preview` (≤400) on `prompt.inject` only — not full text. Also copy `brief_sha12`/`mini_sha12` onto `debug.catalog`.

**Step 4:** Tests PASS. Existing detective goldens: update only if they asserted whole-system sha.

**Step 5:** Commit `feat(detective): slice sha12 for SCOPE BRIEF and MINI-SCHEMA (ZCP-N)`

---

### Task 5: Rich hop records

**Objective:** Each hop carries url, verbatim error, 2000-char snippet, pipeline meta.

**Files:**
- Modify: `src/zeus_client/ports/__init__.py` (`VerbHopResult` + optional `url: str = ""`)
- Modify: `src/zeus_client/adapters/zeus_http/verbs.py` (set `url` on result)
- Modify: `src/zeus_client/application/agent_turn.py` (`_execute_tool_calls` hop_rec)
- Reuse: `extract_pipeline_meta` in `application/projectors/session_trace.py`
- Test: `tests/unit/application/test_agent_turn.py`, `tests/unit/adapters/test_zeus_http_verbs.py`

**Step 1: Failing test** — fake `VerbHopResult` with body `{"meta": {"step_costs": [{"verb": "find", "result_size": 3}]}}` and `error=None`; after `_execute_tool_calls`, hop has `step_costs`, `result_size==3`, `snippet` length can exceed 500, `url` forwarded.

**Step 2:** FAIL — snippet 500, no meta.

**Step 3:**

```python
from zeus_client.application.projectors.session_trace import (
    TRACE_SNIPPET_MAX,
    extract_pipeline_meta,
)
meta = extract_pipeline_meta(body)
text = json.dumps(body) if body else (hop.error or "")
hop_rec = {
    "req_id": hop.req_id,
    "name": name,
    "path_class": "pipeline" if name == "pipeline" else name,
    "status": hop.status_code,
    "ok": hop.ok,
    "ms": ms,
    "url": getattr(hop, "url", "") or "",
    "error": hop.error,
    "snippet": text[:TRACE_SNIPPET_MAX],
    **meta,
}
```

Add `url: str = ""` to `VerbHopResult` (default keeps fakes working). `HttpxZeusPort` already knows the request URL — set it.

**Step 4:** Tests PASS. Adapter unit tests that construct `VerbHopResult(...)` still work (new field defaulted).

**Step 5:** Commit `feat(hops): url, error, snippet 2000, pipeline meta (ZCP-N)`

---

### Task 6: Compact Layer A on `public_trace`

**Objective:** Widget / session-trace see required-four + `via` + `synthetic`, not only summary/confidence.

**Files:**
- Modify: `src/zeus_client/application/agent_turn.py` (`_finish` `layer_map`)
- Optional helper: `src/zeus_client/domain/layer_a.py` `compact_layer_a(layer) -> dict`
- Test: `tests/unit/application/test_agent_turn.py` + existing peel tests must stay green

**Step 1: Failing test** — terminate with full return bag (copy `_return_args()` from the untracked session-join test). Assert:

```python
la = result.debug.public_trace["layer_a"]
assert la["query_decomposition"]["entity"] == "Airport"
assert la["decomposition"]["predicates"]["country"] == "United States"
assert la["via"] == "client_terminate"
assert la["synthetic"] is False
assert "wish_i_knew" not in la
assert "jail_break_attempt" not in la
assert "wish_i_knew" not in result.answer
```

**Step 2:** FAIL — current `layer_map` omits QD.

**Step 3:** Build compact dict from `LayerA` (already parsed). `synthetic=True` when `policy_action=="error"` **and** empty targets / dump heuristic (`looks_like_layer_a_dump(summary)`). `via`: `client_terminate` if return tool; `pipeline_turn_complete` if pipeline terminate. Keep full object on `TurnResult.layer_a`.

**Step 4:** Tests PASS. Detective dump playbook still sees `layer` via `TurnResult` / the compact bag summary.

**Step 5:** Commit `feat(layer-a): compact terminate bag on public_trace (ZCP-N)`

---

### Task 7: `zeus.url`, client version, tokens on the bundle

**Objective:** Item 3 + 8 first-class on `DebugBundle` (tokens already on `public_trace`).

**Files:**
- Modify: `src/zeus_client/application/agent_turn.py` (`run_agent_turn` / `_finish`)
- Modify: `src/zeus_client/api/agent.py` (pass `zeus_url` from `rt.config.zeus.url`)
- Test: `tests/unit/application/test_debug_gather.py`

**Step 1: Failing test** — after a turn, `debug.client_version == zeus_client.__version__`, `debug.tokens["ok"]` follows usage, `debug.target["mode"] == settings.mode`. When `zeus_url=` passed through, `debug.zeus_url` matches.

**Step 2:** FAIL — fields empty.

**Step 3:** Add `zeus_url: str | None = None` kwarg to `run_agent_turn` / `_finish`. Default `client_version` from `zeus_client._version.__version__`. Copy `sum_provider_tokens(steps=steps)` onto `debug.tokens` (same object as `public_trace.tokens`). Target map already built for Detective — also set `debug.target`.

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(debug): stamp zeus.url, client version, tokens (ZCP-N)`

---

### Task 8: Journal `export_ref` on every result

**Objective:** Item 9 — operator can load the redacted journal without knowing Detective.

**Files:**
- Modify: `src/zeus_client/application/agent_turn.py` (`_finish`)
- Modify: `src/zeus_client/api/debug.py` (docstring: `export_journal(turn_id=result.debug.export_ref)`)
- Test: `tests/unit/application/test_debug_gather.py`, `tests/unit/api/test_debug_api.py` if present

**Step 1: Failing test**

```python
assert result.debug.export_ref == result.debug.turn_id
assert result.debug.journal_schema == 1
assert result.debug.journal_event_count >= 2  # turn.started + turn.completed
exp = export_journal_redacted(journal, turn_id=result.debug.export_ref)
assert any(e.get("type") == "turn.started" for e in exp.events)
```

**Step 2:** FAIL — `export_ref` None.

**Step 3:** `export_ref = turn_id`. Do **not** serialize the full journal onto `TurnResult` (payload size). Document the handle. If the runtime journal is the same object `AgentAPI` passed in, `rt.debug.export_journal(turn_id=…)` works after the call.

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(debug): set journal export_ref on TurnResult (ZCP-N)`

---

### Task 9: Support pack includes all nine

**Objective:** Ticket markdown is the human gather pack.

**Files:**
- Modify: `src/zeus_client/application/detective/support_pack.py`
- Modify: `src/zeus_client/application/detective/diagnosis.py` (pass new kwargs)
- Modify: `src/zeus_client/application/detective/build.py` (thread fields)
- Test: `tests/unit/application/test_detective.py`

**Step 1: Failing test** — `build_support_pack(...)` markdown contains headings/lines for:

1. chat / turn / session ids
2. preferred + all req_ids + hop table (name, status, ms, error)
3. target triple + zeus.url + client version
4. catalog flags + tools_count + contract_status
5. inject sha12s
6. hop errors / row signal
7. layer_a via/confidence/policy (not G2)
8. token totals
9. `export_ref`

**Step 2:** FAIL — current pack is headline + ids + playbooks only.

**Step 3:** Extend `build_support_pack` with optional kwargs (all default empty). Keep G2 out. Truncate hop snippets to 200 chars in markdown. `diagnosis.support_pack` stays `{headline, markdown, preferred_req_id, playbook_ids}` plus the new lite fields already there.

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(detective): support_pack covers nine gather fields (ZCP-N)`

---

### Task 10: Wire `SessionLifecycle` into `run_agent_turn` (opt-in)

**Objective:** When `enable_sessions=True` **and** a lifecycle is injected: setup → post identical aggregate `/v2/session/trace` on **tool** `req_id`s (primary last) → commit turn. Soft-fail.

**Files:**
- Modify: `src/zeus_client/application/agent_turn.py`
- Land (was untracked): `tests/unit/application/test_agent_turn_session_join.py` — this **is** the oracle. Adapt names if helpers differ; do not weaken asserts (`req_id` = find hop, compact `layer_a.via == client_terminate`).

**Step 1:** Add the untracked test file (trim to committed APIs). Run it — FAIL (`session_lifecycle` unexpected kwarg).

**Step 2:** Confirm FAIL reason is missing wiring, not fixture bugs.

**Step 3:** Minimal wiring:

```python
async def run_agent_turn(..., session_lifecycle: SessionLifecycle | None = None):
    handle = req.session
    if req.enable_sessions and session_lifecycle is not None:
        try:
            handle = await session_lifecycle.setup(
                chat_request=req.chat_request or {},
                user_message=req.message,
                prior=req.session,
                chat_id=req.chat_id or "",
                turn_id=turn_id,
                mode=settings.mode,
                enable_sessions=True,
                force_trace=bool(settings.force_trace),
            )
        except Exception as exc:
            notes.append(f"session_setup_failed: {exc}")
            handle = req.session
    # ... loop ...
    # after hops + layer compact:
    if req.enable_sessions and session_lifecycle is not None and handle and handle.session_id:
        try:
            await project_session_trace(
                client=session_lifecycle.client,
                handle=handle,
                hops=hops,
                layer_a=compact,
                ...
            )
            commit = await session_lifecycle.commit(handle, ...)
            handle = commit.handle
        except Exception as exc:
            notes.append(f"session_commit_failed: {exc}")
```

Soft-fail only — never change `TurnStatus` because join failed.

**Step 4:** `pytest tests/unit/application/test_agent_turn_session_join.py -q` PASS.

**Step 5:** Commit `feat(session): join tool hops from run_agent_turn (ZCP-N)`

---

### Task 11: `AgentAPI` injects lifecycle + hub base

**Objective:** Default runtime path can actually produce session_id + hub links.

**Files:**
- Modify: `src/zeus_client/runtime.py` (`Services.session_lifecycle`, optional construct)
- Modify: `src/zeus_client/config/models.py` (`DebugPolicy.hub_base_url: str | None = None`)
- Modify: `src/zeus_client/api/agent.py`
- Test: the existing untracked `test_agent_api_enable_sessions_uses_injected_lifecycle` (in T10 file)

**Step 1: Failing test** — `AgentAPI(runtime_with_svc.session_lifecycle).run_turn("hi", enable_sessions=True)` calls `setup`. Second test: `debug.hub_base_url` / `detective.overview.hub_links.session` set when `DebugPolicy.hub_base_url` is set.

**Step 2:** FAIL — `hub_base_url=None`, no lifecycle.

**Step 3:**

```python
# api/agent.py
life = getattr(self._rt.services, "session_lifecycle", None)
result = await run_agent_turn(
    ...,
    session_lifecycle=life,
    hub_base_url=self._rt.config.debug.hub_base_url,
    zeus_url=self._rt.config.zeus.url,
)
```

Do **not** construct `HttpxSessionClient` inside `AgentAPI` if zeus port is missing (tests). Optional later: factory wires lifecycle when `enable_sessions` and HTTP exist — out of scope unless a factory already builds session client. Prefer inject-only this task.

**Step 4:** Tests PASS. Default `enable_sessions=False` tests still skip network.

**Step 5:** Commit `feat(api): AgentAPI forwards lifecycle and hub_base_url (ZCP-N)`

---

### Task 12: `public_trace.session` block

**Objective:** Widgets that already read `trace.session.preferred_req_id` / `req_ids` work without Detective.

**Files:**
- Modify: `src/zeus_client/application/projectors/public_trace.py`
- Modify: `src/zeus_client/application/agent_turn.py` (pass session block; `merge_hop_into_trace_session` already exists)
- Test: `tests/unit/application/test_public_trace.py` (create/extend)

**Step 1: Failing test** — `build_public_trace(..., session_id=..., req_ids=..., preferred=...)` includes:

```python
"session": {
  "id": "sess_1",
  "req_ids": ["req-a"],
  "preferred_req_id": "req-a",
  "contract_status": "match",
}
```

**Step 2:** FAIL — key absent.

**Step 3:** Add optional kwargs to `build_public_trace`; omit `session` entirely when no id and no req_ids (data-plane / offline).

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(trace): public_trace.session gather block (ZCP-N)`

---

### Task 13: Smaller bundle on direct / typeahead

**Objective:** Item 1–3 + 6 + 9 for non-agent hops (single `req_id`).

**Files:**
- Modify: `src/zeus_client/application/data_verb.py` (`VerbResult` additive debug fields **or** nested small `DebugBundle`)
- Modify: `src/zeus_client/application/typeahead.py` similarly if it has a result type
- Test: `tests/unit/application/test_data_verb.py`

**Step 1: Failing test** — `run_data_verb` result exposes `req_id`, `zeus_url` optional, `export_ref`/`turn_id` if journal present. Do **not** invent a fake session.

**Step 2:** FAIL if `VerbResult` has only today's fields.

**Step 3:** Additive: `chat_id`, `turn_id`, `trace_class="direct.read"`, `req_ids=(req_id,)` when known. YAGNI: no Detective briefing on typeahead by default.

**Step 4:** Tests PASS.

**Step 5:** Commit `feat(data): small debug gather on direct hops (ZCP-N)`

---

### Task 14: Docs + `make ci`

**Objective:** Integrators know the nine fields live on `result.debug`, not Hub.

**Files:**
- Create: `docs/DEBUG_GATHER.md` (short: the nine, `export_journal`, session opt-in, never Rewind `/turn`)
- Modify: `docs/VERBS.md` (pointer)
- Modify: skill is **not** edited unless implementer is asked — optional follow-up `zeus-client-python` `references/` note
- Test: no new product tests; run the suite

**Step 1:** Write `docs/DEBUG_GATHER.md` with the locked shape + “client does not need Detective”.

**Step 2:** `make ci` (or `pytest -q -m "not integration"` + ruff + mypy on touched modules).

**Step 3:** Fix only failures this train introduced.

**Step 4:** Commit `docs: E2E debug gather nine fields (ZCP-N)`

---

## Files likely to change

| Path | Why |
| --- | --- |
| `src/zeus_client/domain/messages.py` | `DebugBundle` fields + `to_dict` |
| `src/zeus_client/ports/__init__.py` | `VerbHopResult.url` |
| `src/zeus_client/adapters/zeus_http/verbs.py` | stamp url on hop result |
| `src/zeus_client/application/agent_turn.py` | gather + session join + rich hops |
| `src/zeus_client/application/detective/extract.py` | slice sha |
| `src/zeus_client/application/detective/prompt_checklist.py` | verbs count |
| `src/zeus_client/application/detective/support_pack.py` | nine-section markdown |
| `src/zeus_client/application/detective/build.py` / `diagnosis.py` / `overview.py` | thread fields |
| `src/zeus_client/application/projectors/public_trace.py` | `session` + tokens already |
| `src/zeus_client/application/data_verb.py` | small bundle |
| `src/zeus_client/api/agent.py` | lifecycle + hub + zeus_url |
| `src/zeus_client/runtime.py` / `config/models.py` | `hub_base_url`, optional lifecycle slot |
| `docs/DEBUG_GATHER.md` | integrator contract |
| `tests/unit/domain/test_debug_bundle.py` | T1 |
| `tests/unit/application/test_debug_gather.py` | T2/T7/T8 |
| `tests/unit/application/test_agent_turn_session_join.py` | T10/T11 (land untracked oracle) |

---

## Tests / validation

Per-task pytest first (RED-GREEN). After T12:

```bash
.venv/bin/pytest -q -m "not integration" \
  tests/unit/domain/test_debug_bundle.py \
  tests/unit/application/test_debug_gather.py \
  tests/unit/application/test_agent_turn.py \
  tests/unit/application/test_agent_turn_session_join.py \
  tests/unit/application/test_detective.py \
  tests/unit/application/test_session_lifecycle.py
```

Train done when:

- [ ] Default `run_agent_turn` (no sessions) still returns items **1–9** except `session_id` (honestly `None`) and empty `req_ids` on no-hop turns
- [ ] `enable_sessions=True` + injected lifecycle → `session_id` + `public_trace.session.req_ids` + trace POST uses **tool** `req_id`
- [ ] `support_pack.markdown` contains all nine sections
- [ ] `rt.debug.export_journal(turn_id=result.debug.export_ref)` returns that turn
- [ ] `make ci` green
- [ ] No G2 in `answer` / compact `layer_a` / support pack
- [ ] `AgentAPI` default `enable_sessions=False` does not open `:8080`

---

## Risks, tradeoffs, open questions

| Risk | Mitigation |
| --- | --- |
| `DebugBundle` construct sites break | Additive defaults only |
| Session join in `run_agent_turn` pulls HTTP into unit tests | Inject FakeLifecycle; default off |
| Snippet 2000 × N hops bloats API | Cap already exists; do not attach full journal |
| Whole-system sha tests exist | Update those goldens in T4 only |
| `VerbHopResult.url` churn | Default `""` |
| Hub base unknown | `DebugPolicy.hub_base_url` optional; links omitted when unset |
| Untracked session-join test drifts | Land it as T10 SoT; do not rewrite expected compact `layer_a` |

**Open questions (defaults if unanswered):**

1. Should `export_ref` be only `turn_id`, or also a runtime-held snapshot id? **Default: `turn_id`.**
2. Should factory auto-build `SessionLifecycle` when HTTP exists? **Default: no this train — inject only.**
3. Create Jira epic now or after first green commit? **Default: create epic + stories before T1 (ZCP hygiene).**

---

## Acceptance (product)

An integrator who has never heard of Detective can, from one `TurnResult`:

1. Read `debug.chat_id` / `turn_id` / `session_id`
2. Read `debug.req_ids` + `preferred_req_id` + hop `name`/`path_class`/`url`
3. Read `debug.target` + `debug.zeus_url` + `debug.client_version`
4. Read `debug.catalog` (brief/mini/tools_count) + `debug.contract_status`
5. Read `debug.detective.prompt.inject` sha12s (or `debug.catalog` shas)
6. Read `debug.hops[]` verb/status/ms/error/rows meta
7. Read peeled `answer` + compact `public_trace.layer_a`
8. Read `debug.tokens`
9. Call `rt.debug.export_journal(turn_id=debug.export_ref)` for the redacted tape

and paste `debug.detective.diagnosis.support_pack.markdown` into a ticket.
