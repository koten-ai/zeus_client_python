# Reference: TravelPlan (`demo_travel_sample`)

**Status**: Draft  
**Role**: Canonical reference implementation for this kit  
**App root**: repository root of `demo_travel_sample`

---

## 1. Why this exists

TravelPlan is a complete vertical demo. Use it when recipes need a concrete file — do not copy travel domain blindly; parameterize via [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md).

---

## 2. Recipe → file map

| Recipe | TravelPlan path |
|--------|-----------------|
| R01 | `src/travel_planner/zeus_config.py`, `__init__.py` |
| R02 | `src/travel_planner/async_runner.py` |
| R02b | *(no FastAPI app — library patterns only)* |
| R03 | `async_runner.startup` / `shutdown` |
| R04 | `async_runner._sync_chat_requests_on_startup` |
| R05 | `src/travel_planner/search.py` |
| R06 | `src/travel_planner/output_schema.py` |
| R07 | `search.py`, `results_parser.py`, `answer_parser.py` |
| R08 | `chat_store.py`, `search.py` |
| R09 | `src/travel_planner/app.py` |
| R10 | `static/zeus_client_chat_trace.js`, templates, `build_tool_order` |
| R11 | `Dockerfile`, `docker-compose.yml` |
| R12 | `scripts/verify_config.py` |

---

## 3. File-by-file “why”

| File | Why it exists |
|------|----------------|
| `zeus_config.py` | Import-time env for project layout |
| `async_runner.py` | Flask ↔ async client bridge |
| `search.py` | Domain agent + result waterfall |
| `output_schema.py` | Card allowlist |
| `results_parser.py` | Trace → cards |
| `answer_parser.py` | Markdown fallback |
| `chat_store.py` | Multi-turn + session ids |
| `app.py` | Minimal API |
| `templates/index.html` | Search UI + trace embed |
| `static/*` | CSS/JS + vendored trace |
| `data/chat_requests/` | Catalog snapshots |
| `config.example.json` | Operator template |
| `tests/*` | Acceptance patterns |

<!-- TODO: One-paragraph annotations per file -->

---

## 4. Guides (internal)

| Guide | Topic |
|-------|--------|
| `.grok/guides/TRAVEL_PLANNER.md` | App overview |
| `.grok/guides/ZEUS_CLIENT_INTEGRATION.md` | Client wiring |
| `.grok/guides/DEMO_OUTPUT_SCHEMA.md` | Structured cards |
| `.grok/guides/MARKDOWN_ANSWER_PARSER.md` | Markdown fallback |

---

## 5. How agents should use this reference

1. Implement from kit recipes first  
2. Open the mapped file only if the recipe is incomplete  
3. Strip travel-specific strings when building another domain  
