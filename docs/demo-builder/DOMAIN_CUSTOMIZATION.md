# Domain customization

**Status**: Draft  
**v1 policy**: Travel preset only ([presets/travel.md](presets/travel.md)); all other verticals use this guide.

---

## 1. Knob table

| Knob | Travel example | How to change |
|------|----------------|---------------|
| Sample bucket/scope/collection | `travel-sample/_default/_default` | `samples` + `default_sample` in config |
| Mode / catalog | `travel_booking` | `default_mode` + ensure chat_request exists |
| Domain prompt prefix | “Find travel destinations…” | rewrite in search wrapper |
| `output_schema` entity types/fields | Hotel, Destination, Airport | match scope brief / UI cards |
| Result mappers | name, description, image | map synonyms → card model |
| UI copy | destinations | domain language |
| Example queries | beaches, budget, region | supply 3+ for acceptance |

---

## 2. Deriving `output_schema`

<!-- TODO: precedence: arg → chat_request → MINI-SCHEMA; reserved fields -->

Precedence in client (highest first):

1. `output_schema` argument to `run_agent`
2. `guidance.injections.output_schema` in chat_request
3. Live MINI-SCHEMA from scope brief

Reserved fields often kept: `id`, `doc_key`, `entity_type`.

---

## 3. Result mapper strategy

<!-- TODO: field synonym lists pattern from results_parser / output_schema -->

Prefer an allowlist of display fields; map common aliases (`image_url` → `image`, etc.).

---

## 4. Worked sketch: non-travel (beer analytics)

<!-- TODO: short non-runnable sketch — mode, sample, schema, prompt, card fields -->

Not a full app. Illustrates knob changes only.

---

## 5. Domain swap checklist

- [ ] Config `samples` / `default_sample` / `default_mode` updated
- [ ] Catalog present or sync enabled for mode
- [ ] `scope_contracts` keys match
- [ ] Prompt prefix rewritten
- [ ] `output_schema` rewritten
- [ ] Parsers/mappers updated
- [ ] UI strings updated
- [ ] Example queries + acceptance smoke pass
