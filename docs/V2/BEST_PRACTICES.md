# Zeus Client V2 — Engineering Best Practices

**Companion to:** [DESIGN.md](./DESIGN.md), [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md), [SECURITY.md](./SECURITY.md)

This document is the engineering standard for implementing and evolving Zeus Client V2. Treat it as review criteria.

---

## 1. Coding standards

### 1.1 Language and style

| Rule | Detail |
| --- | --- |
| Python | ≥ 3.11; use modern typing (`list[str]`, `X \| None`, `TypedDict` where helpful) |
| Formatting | `ruff format` (or Black-compatible) — no style bikeshedding in PR |
| Lint | `ruff check` clean on touched files |
| Types | Public surface + domain + application must typecheck; adapters best-effort |
| Line budget | Prefer &lt; 400 LOC per module; hard smell &gt; 600 without justification |
| Functions | Prefer &lt; 50 lines; orchestrators may be longer if decomposed into named steps |
| Mutability | Domain models frozen where practical; journals append-only |
| Inheritance | Avoid; use protocols + composition |
| Globals | Forbidden for HTTP, auth, config (inject via runtime) |
| Comments | Explain *why* and Zeus constraints; do not narrate code |
| TODOs | Link issue; no bare `TODO` in GA paths |

### 1.2 Naming

| Kind | Convention | Example |
| --- | --- | --- |
| Modules | snake_case | `session_lifecycle.py` |
| Classes | PascalCase | `ExecutionJournal` |
| Functions | snake_case | `run_turn` |
| Public data APIs | `run_<zeus_verb>` or facade methods | `rt.data.find` |
| Error codes | STABLE_SCREAMING | `ZEUS_BOUNDARY_MISCONFIG` |
| Events | `domain.action` | `zeus.hop` |
| Env vars | `ZEUS_CLIENT_*` | `ZEUS_CLIENT_FORCE_TRACE` |

**Do not** invent product nicknames for new public APIs (`run_fast_*`).

### 1.3 Imports

- Domain must not import adapters or `httpx`.  
- Application may import domain + ports only.  
- Adapters import domain DTOs freely.  
- `api/` is a thin shell — no business logic.

### 1.4 Example — good vs bad

```python
# BAD: god function, positional soup, mutable global trace
async def run_agent(url, zcfg, base_url, key, model, ver, mode, b, s, c, msg, prior):
    trace = {}
    ...

# GOOD: typed request, injected services, journal spine
async def run(self, req: TurnRequest) -> TurnResult:
    journal = self._journals.start(self._ids.turn_id())
    journal.append(turn_started(...))
    ...
    return TurnResult(...)
```

---

## 2. API design

### 2.1 Principles

1. **Discoverability:** `runtime.agent` / `.data` / `.catalog` / `.debug`  
2. **Stability:** additive change preferred; breaking changes only in major  
3. **Explicit targets:** `DataTarget` on calls; config supplies defaults only  
4. **One obvious way** for common tasks; power APIs secondary  
5. **Failure is typed:** results or exceptions with `ErrorCode` — not magic tuples  
6. **Async-first:** network I/O is `async`; pure helpers sync  
7. **Idempotent naming:** methods do what they say (`search` typeahead ≠ raw `search_verb`)

### 2.2 Result objects

```python
# Preferred
result = await rt.agent.run_turn(...)
if result.status is TurnStatus.OK:
    use(result.answer)
else:
    handle(result.error)

# Avoid
answer, trace, turns, meta = await run_agent(...)  # V1 legacy only
```

### 2.3 Options objects

Use small frozen dataclasses for optional bundles:

```python
SearchOptions(entity_type="Business", limit=8, fts_timeout_ms=2000)
```

Avoid `**kwargs` on public APIs.

### 2.4 Compatibility

- Deprecations: `DeprecationWarning` + docs + removal window ≤ 1 minor when possible for soft deprecations; majors for hard breaks.  
- Do not keep dual-read forever.

### 2.5 What not to expose

| Forbidden public | Reason |
| --- | --- |
| `run_pipeline` | Ungoverned multi-step side effects |
| Admin unregister helpers | Graph wipe footgun |
| Raw unredacted journal mutators | Integrity |
| Process-global `get_client()` | Testing/multi-tenant |

---

## 3. Error handling

### 3.1 Rules

1. Raise **typed** `ZeusClientError` subclasses at boundaries.  
2. Every error has stable `ErrorCode`.  
3. Set `retryable` deliberately — default **False** if unsure.  
4. Chain causes (`raise X from e`) without leaking secrets in messages.  
5. Soft-fail projectors: catch, journal `error.raised`, continue.  
6. Never bare `except:` / swallow without journal note.  
7. Map HTTP status + body signatures to codes in **one** classifier module.

### 3.2 Example classifier sketch

```python
def classify_zeus_tool_error(status: int, body_text: str) -> ErrorInfo:
    if "unknown boundary" in body_text:
        return ErrorInfo(ErrorCode.ZEUS_BOUNDARY_MISCONFIG, retryable=False, ...)
    if "search_timeout" in body_text:
        return ErrorInfo(ErrorCode.ZEUS_FTS_TIMEOUT, retryable=True, ...)
    ...
```

### 3.3 User-facing vs developer-facing

| Layer | Content |
| --- | --- |
| `TurnResult.answer` | Product-safe natural language |
| `TurnResult.error.public_message` | Safe short string |
| Logs / journal | Codes + redacted detail |
| Detective support pack | Operator markdown (redacted) |

---

## 4. Logging

| Practice | Detail |
| --- | --- |
| Library logger | `logging.getLogger("zeus_client")` — never configure root in library code |
| Structured fields | `turn_id`, `req_id`, `error_code`, `component`, `latency_ms` |
| Levels | See DESIGN §4.9 |
| Bodies | Dual-gated (profile + flag) |
| Performance | No DEBUG string formatting in hot paths when logger disabled (`logger.isEnabledFor`) |

Apps own handlers/formatters.

---

## 5. Instrumentation

### 5.1 Mandatory instrumentation points

| Point | Span / event |
| --- | --- |
| Turn | `turn.started` / `completed` |
| Auth | span `zeus.auth` |
| Catalog load | span `catalog.load` |
| Session create/rehydrate/turn | spans |
| Each LLM call | span `llm.complete` |
| Each Zeus hop | span `zeus.hop` + event with `req_id` |
| Projectors | events |

### 5.2 Metrics (recommended names)

```text
zeus_client_turns_total{status,mode}
zeus_client_zeus_hops_total{verb,status_class}
zeus_client_zeus_hop_latency_ms{verb}
zeus_client_llm_latency_ms{model}
zeus_client_llm_tokens_total{direction}
zeus_client_errors_total{code}
zeus_client_rate_limited_total{surface}
```

### 5.3 Correlation

Always propagate:

- `turn_id`, `chat_id`, `call_id`  
- Zeus `req_id` when present  
- `session_id` when present  

---

## 6. Testing

### 6.1 Pyramid

| Layer | % effort | Tools |
| --- | --- | --- |
| Unit (domain/application) | 60% | pytest, fakes |
| Contract (adapters) | 25% | respx |
| Integration | 10% | live lab, marked |
| E2E demo | 5% | optional CI job |

### 6.2 TDD expectations

- New domain behavior: **red → green → refactor**  
- Bugfix: regression test first  
- Oracle tests: freeze V1 behavioral fixtures when porting  

### 6.3 Test quality rules

| Rule | Reason |
| --- | --- |
| No real network in unit/contract | Determinism |
| No sleeps for sync | Use fake clock |
| Table-driven URL/verb matrices | Coverage without spam |
| Golden JSON for detective/journal export | Schema stability |
| Assert `ErrorCode` not substrings alone | Stability |
| Redaction tests mandatory for new payload paths | Security |
| Smoke imports for public exports | Prevent demo ImportError |

### 6.4 Example test layout

```text
tests/unit/domain/journal/test_append.py
tests/unit/application/detective/test_build.py
tests/contract/adapters/zeus_http/test_verb_urls.py
tests/integration/test_session_live.py
tests/fixtures/journals/multi_hop_agent.json
```

### 6.5 Async

- `pytest-asyncio` auto mode  
- Function-scoped event loops  
- Ensure httpx client closed in fixtures  

---

## 7. Performance optimization

### 7.1 Principles

1. Measure with spans before optimizing.  
2. Keep typeahead off the agent path.  
3. Bound journal payload sizes.  
4. Reuse HTTP connections per runtime.  
5. Avoid O(n²) detective playbooks over huge bodies — use previews.  
6. Do not deepcopy entire catalogs each turn without need.  
7. Prefer sequential tool execution by default (correctness & Zeus load).

### 7.2 Budgets

See IMPLEMENTATION_GUIDE performance targets. Fail CI microbench only if catastrophic regression (&gt;2×) on pure functions.

### 7.3 Anti-patterns

| Anti-pattern | Fix |
| --- | --- |
| Logging full bodies at INFO | Redacted previews |
| Creating new httpx client per hop | Runtime pool |
| Agent per keystroke | `rt.data.search` |
| Busy poll Hub | Opt-in hydrate once |
| Unbounded prior_turns | App-side windowing |

---

## 8. Debugging conventions

### 8.1 Operator path (external client)

```text
1. Read TurnResult.debug.hub.session_url
2. Inspect detective Overview / Diagnosis / Prompt
3. Drill preferred_req_id in Hub
4. If pipeline mid-rich: trust storage/spans + session_trace.tool_hops
5. Export journal for offline diff / replay
```

### 8.2 Developer path (library)

```text
1. Reproduce with fake ports + recorded dialogue
2. Assert journal event sequence
3. Only then hit live lab
```

### 8.3 Conventions

| Convention | Detail |
| --- | --- |
| Never unify hops under one client `X-Zeus-Req-Id` | Collision |
| Prefer session deep link in UIs | Not thin `/turn` req |
| Client prompt checklist is SoT externally | Hub tool-hop inject tiles may false-fail |
| Note Zeus instrumentation gaps honestly | Don’t “fix” with fake AI.Calls |

### 8.4 Support pack

Always include when filing bugs:

- `turn_id`, `session_id`, `preferred_req_id`  
- client version, zeus engine version if known, base_id  
- redacted detective support_pack markdown  
- error codes  

---

## 9. Versioning

### 9.1 Three clocks (never conflate)

| Clock | Source of truth |
| --- | --- |
| Zeus engine | Server `Version` |
| chat_request BASE | `base-N` packs / COMPAT |
| Client package | `pyproject.toml` + `__version__` |

### 9.2 Semver for the client

| Bump | When |
| --- | --- |
| MAJOR | Breaking public API / journal schema incompatible without adapter |
| MINOR | Additive APIs, new playbooks, new events (consumers ignore unknown) |
| PATCH | Bugfixes, redaction fixes, perf |

Journal: `journal_schema: 1` additive; breaking event semantics → schema 2 + migrator.

### 9.3 Pre-release tags

`2.0.0aN` → `2.0.0bN` → `2.0.0rcN` → `2.0.0`

---

## 10. Documentation expectations

| Change type | Required docs |
| --- | --- |
| Public API | Docstrings + README snippet + changelog |
| Event schema | DESIGN or `docs/V2/JOURNAL_SCHEMA.md` (add when implemented) |
| Security-relevant | SECURITY.md + tests |
| Detective playbook | Playbook table + fixture |
| Migration impact | MIGRATION notes |
| Zeus constraint discovery | Short reference under `docs/` or skill update |

Docstrings: purpose, parameters, raises, examples for public methods.

Keep V2 design docs updated when architecture decisions change — **do not** leave DESIGN stale.

---

## 11. CI/CD recommendations

### 11.1 PR pipeline

```text
ruff check/format
typecheck (public + domain + application)
pytest -q -m "not integration"
pip audit / safety (non-blocking warn → blocking on GA)
coverage report (fail under threshold)
```

### 11.2 Nightly / manual

```text
pytest -m integration  # lab credentials
demo_yelp smoke against monorepo path
```

### 11.3 Release pipeline

```text
full pytest
build sdist/wheel
twine check
tag vX.Y.Z
publish
generate SBOM
GitHub release notes from changelog
```

### 11.4 Branching

| Branch | Use |
| --- | --- |
| `main` | Stable releases |
| `feat/v2` | V2 integration branch |
| `feat/*` | Features from latest tip |
| `fix/*` | Fixes |

Require PR review for `domain/`, `security/`, public `api/`.

---

## 12. Release strategy

1. **Alpha:** journal + data plane usable internally  
2. **Beta:** agent + detective; demo dogfood  
3. **RC:** API freeze; only bugs  
4. **GA:** publish 2.0.0; compat shim optional  
5. **Post-GA:** remove compat within one minor if usage low  

Changelog format: Keep a Changelog — categories Added/Changed/Fixed/Security.

Version sync checklist:

- [ ] `pyproject.toml`  
- [ ] `__version__`  
- [ ] CHANGELOG  
- [ ] tag  

---

## 13. Monitoring (consumer guidance)

Library emits metrics/logs; apps should:

| Signal | Alert idea |
| --- | --- |
| `errors_total{code=ZEUS_AUTH_*}` | Auth outage |
| Spike `ZEUS_FTS_TIMEOUT` | FTS/index health |
| `ZEUS_BOUNDARY_MISCONFIG` | Config regression |
| Turn latency p95 | SLA |
| Rate limited typeahead | UX degradation |

Wire OTLP exporter in staging first.

---

## 14. Telemetry & observability

### 14.1 Layers

| Layer | Mechanism |
| --- | --- |
| Product debug | Detective + Hub links |
| Engineering | Journal export + replay |
| SRE | Metrics + logs + optional OTLP |

### 14.2 Privacy

- Prod: minimal payloads, strict redaction  
- Sampling: allow journal full-fidelity sample rate config for canaries  
- Never ship secrets to third-party APM  

### 14.3 Cardinality

Avoid high-cardinality labels (`user_id`, full `req_id`) on metrics — use logs/journal for those.

---

## 15. Concurrency & cancellation

| Practice | Detail |
| --- | --- |
| Honor `asyncio.cancellation` | Close spans as errored |
| Runtime close | Abort or drain in-flight turns (document behavior) |
| Thread safety | Runtime is not thread-safe; one event loop |
| Shared auth cache | `asyncio.Lock` per key |

---

## 16. Plugin author guidelines

1. Register in application startup — explicit.  
2. Keep middleware fast (&lt; 1ms CPU).  
3. Journal annotations instead of silent behavior changes.  
4. Never log secrets.  
5. Provide unit tests with fake runtime services.  
6. Declare capabilities needed.  

---

## 17. Code review checklist

Reviewer verifies:

- [ ] Matches hexagonal boundaries (no httpx in domain)  
- [ ] Journal events for new external I/O  
- [ ] Redaction considered  
- [ ] Typed errors with codes  
- [ ] Tests at right layer  
- [ ] Public API intentional and documented  
- [ ] No pipeline public exposure  
- [ ] No invented contract stamps  
- [ ] Session isolation preserved  
- [ ] Performance obvious footguns absent  
- [ ] Docs/changelog if user-visible  

---

## 18. Git hygiene

| Practice | Detail |
| --- | --- |
| Atomic commits | One logical change |
| Messages | Imperative; reference issue |
| No secrets in history | Use git-secrets/pre-commit optional |
| Fixtures | Redacted only |

---

## 19. Examples and demos

- Examples must run with `ZeusRuntime` and fail clearly without config.  
- Prefer `examples/` scripts over README-only code.  
- Demos consume **stable public API only** — not `application.*`.  
- When monorepo path-installs the client, keep smoke imports green.

---

## 20. Layer A, policy, and product safety

| Rule | Detail |
| --- | --- |
| Peel terminate bags | `answer` is user-facing only |
| Policy refuse | May replace answer with `ui_text` |
| Artifacts | scores / wish_i_knew stay out of chat UI |
| Tool JSON | untrusted |
| Jailbreak dual scores | Do not overwrite each other |

---

## 21. Catalog & contract discipline

| Rule | Detail |
| --- | --- |
| Hash stability | Prove inject doesn’t change hash when required |
| Fail closed paths | No silent cross-scope catalog |
| Preserve local consistent stamps | Sync rules tested |
| base packs | Offline fixtures OK unstamped; prod catalogs stamped |

---

## 22. Working with Zeus Engine constraints

Document new server quirks in:

1. PR description  
2. Short `docs/` note or detective playbook  
3. Skill updates if ops-facing  

Do not paper over server bugs with unbounded client heuristics without an exit criteria.

---

## 23. Accessibility of debug UX (for host apps)

When embedding debug:

- Keyboard-reachable links to Hub  
- Don’t flash secret-bearing raw JSON in prod UI  
- Prefer detective Overview KPIs for non-engineers  

---

## 24. Summary table — “always / never”

| Always | Never |
| --- | --- |
| Journal external I/O | Invent contract stamps |
| Redact before export | Log Authorization headers |
| Typed ErrorCode | Bare except swallow |
| Session deep links for multi-hop | Reuse one req_id for all hops |
| Typeahead on data plane | Agent on keystroke |
| Tests for redaction paths | Commit live secrets/fixtures with creds |
| Freeze public models carefully | Expose `run_pipeline` |
| Soft-fail detective | Fail user turn on projector bugs |

---

## 25. Continuous improvement

After each production incident:

1. Add `ErrorCode` if missing  
2. Add playbook if pattern repeats  
3. Add regression test  
4. Update SECURITY or DESIGN if assumption wrong  

Quarterly: dependency audit, API usage review (what to deprecate), journal schema review.
