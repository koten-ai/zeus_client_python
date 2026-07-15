# UI contract

**Status**: Draft  
**Related**: [API_CONTRACT.md](API_CONTRACT.md), [TRACE_PANEL.md](TRACE_PANEL.md)

---

## 1. Stack defaults

| Layer | Default (TravelPlan) | Allowed alternatives |
|-------|----------------------|----------------------|
| Server templates | Jinja2 + Flask | FastAPI templates or SPA |
| CSS | Tailwind + DaisyUI (CDN or build) | Other CSS, keep layout goals |
| Client JS | Vanilla JS | Same API contract |

---

## 2. Required UX surfaces

1. **Search form** — textarea + submit  
2. **Result cards** — from `results[]`  
3. **Answer / summary** — from `answer` (markdown optional)  
4. **Trace control** — open floating debug panel  
5. **Error state** — show API `error` message  
6. **Empty state** — no results but successful response  

---

## 3. JSON fields the frontend consumes

| Field | UI use |
|-------|--------|
| `results[]` | Card grid |
| `results[].name` (or mapped) | Title |
| `results[].description` | Body |
| `results[].image` | Thumbnail (optional) |
| `answer` | Summary region |
| `trace` | Trace panel payload |
| `tool_order` | Chart axes |
| `chat_id` | Follow-up searches |
| `error` | Error banner |

<!-- TODO: Exact card field mapping from results_parser / app.js -->

---

## 4. Empty / error states

<!-- TODO: copy and behavior -->

- Loading while `POST /api/search` in flight  
- Empty `results` with non-empty `answer`  
- Network / 4xx / 5xx  

---

## 5. Accessibility (minimum)

<!-- TODO -->

- Form labels  
- Disabled submit while loading  
- Focus management optional for v1  
