# Building a demo

**Status**: Draft  
**Audience**: Coding agents and human integrators  
**Related**: [AGENTS.md](AGENTS.md), [ACCEPTANCE.md](ACCEPTANCE.md)

---

## 1. Goal & success criteria

<!-- TODO: Expand checkbox list from plan §1 -->

- [ ] Natural-language search UI + HTTP API
- [ ] `kotenai-zeus-client` agent loop (`run_agent`)
- [ ] Domain-specific result cards + structured extraction
- [ ] Multi-turn chat store + durable Zeus sessions
- [ ] Floating Zeus chat-trace panel (vendored JS)
- [ ] Config/env bootstrap, catalog sync, Docker
- [ ] Unit tests + smoke acceptance green

**Definition of done**: [ACCEPTANCE.md](ACCEPTANCE.md)

---

## 2. What this kit is / is not

### Is

- A recipe book to productize demos **like** TravelPlan
- Parameterized for other domains via [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md)
- Flask **and** FastAPI integration patterns

### Is not

- A full Zeus Engine / OpenAPI reference (use Zeus docs)
- A full Python SDK reference (use `zeus_client_python` + GitBook Zeus Client)
- A second shipped demo app (TravelPlan is the reference implementation)
- Beer/retail preset packs (v1: travel + customization only)

---

## 3. Operator inputs (fill before generation)

| Input | Example | Required |
|-------|---------|----------|
| Zeus base URL | `http://localhost:8080` | yes |
| Auth mode + credentials | basic / demo user | yes |
| Sample bucket/scope/collection | `travel-sample/_default/_default` | yes |
| Agent mode(s) | `travel_booking` | yes |
| Contract bindings | mode → contract_id/hash | recommended |
| LLM base_url + api_key + model | xAI / OpenAI | yes |
| Domain entity types + card fields | Hotel: name, description, image | yes |
| Example NL queries (3+) | "warm beaches under $2000" | yes |
| Install mode | monorepo path vs wheel | yes |
| Web framework | Flask (default) / FastAPI | optional |

---

## 4. Non-negotiable rules

1. Set env (`ZEUS_CLIENT_CONFIG_DIR`, etc.) **before** any `import zeus_client`
2. Use real Zeus + real LLM — do not invent fake Zeus APIs or alternate agent frameworks
3. Prefer library APIs: `run_agent`, `load_config`, `resolve_*`, `sync_chat_requests`, `build_tool_order`
4. App owns chat store; pass `zeus_session_id` / `zeus_round` for multi-turn
5. Use `output_schema` for UI cards — do not dump full Zeus documents
6. Vendor `zeus_client_chat_trace.js` into static assets by default
7. Never commit live API keys

See also [ANTI_EXAMPLES.md](ANTI_EXAMPLES.md).

---

## 5. Phased build order

```text
Phase 0  Collect human inputs (PREREQUISITES + domain knobs)
Phase 1  Scaffold project tree + pyproject + config.example (SCAFFOLD)
Phase 2  zeus_config + package __init__ import order (R01)
Phase 3  async lifecycle — Flask R02–R04 or FastAPI R02b + R03–R04
Phase 4  output_schema + domain search wrapper (R05–R07)
Phase 5  chat_store multi-turn (R08)
Phase 6  HTTP routes per API_CONTRACT (R09)
Phase 7  UI per UI_CONTRACT + TRACE_PANEL (R10)
Phase 8  Docker compose (R11)
Phase 9  Tests + run ACCEPTANCE checklist
Phase 10 Write demo README (structure from TravelPlan README)
```

Detail: [RECIPES.md](RECIPES.md), [SCAFFOLD.md](SCAFFOLD.md)

---

## 6. Where to read next

| Role | Next |
|------|------|
| Agent | [PREREQUISITES.md](PREREQUISITES.md) → [SCAFFOLD.md](SCAFFOLD.md) |
| Architect | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Domain swap | [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md) |
| Stuck | [REFERENCE_TRAVELPLAN.md](REFERENCE_TRAVELPLAN.md) then TravelPlan source |

---

## 7. Acceptance

Complete [ACCEPTANCE.md](ACCEPTANCE.md) before declaring the demo done.
