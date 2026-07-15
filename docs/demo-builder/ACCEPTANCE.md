# Acceptance

**Status**: Draft  
**Related**: [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md), [ANTI_EXAMPLES.md](ANTI_EXAMPLES.md)

**Done** = sections below green (or residual gaps listed with owner).

---

## 1. Automated tests

- [ ] Parser unit tests (no live Zeus)
- [ ] API tests with mocked `run_agent`
- [ ] Async runner / lifespan smoke (mocked)
- [ ] `pytest` passes for non-integration suite

<!-- TODO: Point at TravelPlan tests/ patterns -->

Integration tests (optional live):

- [ ] Marked `@pytest.mark.integration`
- [ ] Documented how to skip in CI

---

## 2. Manual smoke

- [ ] `cp config.example.json config.json` + keys set  
- [ ] App starts (`python -m …` or `docker compose up --build`)  
- [ ] `GET /` renders search UI  
- [ ] `POST /api/search` with sample query returns:
  - [ ] non-empty `answer` **or** non-empty `results`
  - [ ] `trace` present
  - [ ] `chat_id` present
- [ ] Follow-up with same `chat_id` continues session when durable sessions on  
- [ ] Trace panel opens and shows activity  
- [ ] Cards render when structured rows available  

---

## 3. Config verification

- [ ] Zeus URL reachable from app environment  
- [ ] Catalog for `default_mode` present  
- [ ] LLM key accepted (no auth error on first call)  
- [ ] Optional: R12 verify script  

---

## 4. Troubleshooting matrix

| Symptom | Likely cause | Fix | Doc |
|---------|--------------|-----|-----|
| `HTTP client not initialised` | No `init_http` | Startup lifecycle | R03 |
| `no chat_request file for mode` | Missing catalog | Sync / ship file | CATALOGS |
| `no Zeus URL configured` | Empty config | Edit config.json | CONFIG |
| `llm_provider has no api_key` | Empty key | Set key | CONFIG |
| Empty cards | No structured rows / schema | output_schema + parsers | R06–R07 |
| Session 404 | `/v1/session` vs `/v2` | Upgrade client | PREREQUISITES |
| Docker can't reach Zeus | localhost in container | host.docker.internal | PREREQUISITES |
| Import-order bugs | Early zeus_client import | R01 | CONFIG |

<!-- TODO: Expand from TravelPlan README Troubleshooting -->

---

## 5. AI self-repair loop

```text
Fail symptom
  → match troubleshooting row
  → open linked recipe/doc
  → apply fix
  → re-run smoke §2
  → do not invent new architecture
```

---

## 6. Residual gaps template

| Gap | Owner | Follow-up |
|-----|-------|-----------|
| | | |
