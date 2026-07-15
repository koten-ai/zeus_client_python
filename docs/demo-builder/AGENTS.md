# AGENTS — Demo Builder Kit

**Status**: Draft  
**Audience**: Coding agents only (keep terse)

---

## Mission

Build a productized Zeus demo app (NL search UI + agent loop + cards + trace panel) using **only** this kit and `kotenai-zeus-client`. TravelPlan (`demo_travel_sample`) is the reference implementation when recipes are incomplete.

---

## Load order

1. This file  
2. [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md)  
3. [PREREQUISITES.md](PREREQUISITES.md)  
4. [SCAFFOLD.md](SCAFFOLD.md) + `templates/`  
5. [CONFIG.md](CONFIG.md) + [RECIPES.md](RECIPES.md)  
6. [API_CONTRACT.md](API_CONTRACT.md) / [UI_CONTRACT.md](UI_CONTRACT.md) / [TRACE_PANEL.md](TRACE_PANEL.md)  
7. [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md) if not travel  
8. [ACCEPTANCE.md](ACCEPTANCE.md)

---

## Hard constraints

- Env before `import zeus_client` (R01)
- Real Zeus + LLM; no mock engine as the primary path
- Prefer: `run_agent`, `load_config`, `resolve_zeus_config`, `resolve_llm_provider_config`, `sync_chat_requests`, `build_tool_order`
- Flask **or** FastAPI (document both; match operator choice)
- Trace panel: **vendor** `zeus_client_chat_trace.js` (CDN only if operator requests)
- No secrets in git
- Do not invent Zeus HTTP paths; client library owns dispatch

---

## Build phases (short)

0 Inputs → 1 Scaffold → 2 zeus_config → 3 lifecycle → 4 search+schema → 5 chat store → 6 API → 7 UI+trace → 8 Docker → 9 tests → 10 README

Full list: [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) §5

---

## Done =

All checks in [ACCEPTANCE.md](ACCEPTANCE.md) pass (or residual gaps documented with owner).

---

## When stuck

1. [ANTI_EXAMPLES.md](ANTI_EXAMPLES.md)  
2. [REFERENCE_TRAVELPLAN.md](REFERENCE_TRAVELPLAN.md)  
3. Concrete files under `src/travel_planner/` in this monorepo  
4. Do **not** invent parallel agent frameworks
