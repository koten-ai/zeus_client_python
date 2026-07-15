# Preset: Travel (TravelPlan)

**Status**: Draft  
**v1**: Only domain preset shipped with the kit  
**Reference app**: `demo_travel_sample`

---

## 1. Product one-liner

Natural-language travel preferences → destination cards from Zeus `travel-sample`, with LLM agent loop and trace panel.

---

## 2. Knob values

| Knob | Value |
|------|--------|
| Sample | `travel-sample` / `_default` / `_default` |
| Mode | `travel_booking` |
| API version | `v2` |
| Entity types (schema) | Hotel, Destination, Airport |
| Card fields | name, description, image (+ synonyms) |
| Prompt theme | Find destinations matching user preferences |

---

## 3. Config sketch

See repo root `config.example.json` and [templates/config.example.json](../templates/config.example.json).

<!-- TODO: Paste travel-specific samples / modes / scope_contracts excerpt -->

---

## 4. Example queries

- warm beaches in Europe under $2000  
- tropical destinations with great food  
- family-friendly cities with good transit  

---

## 5. Kit mapping

| Concern | Doc / recipe |
|---------|----------------|
| Full architecture | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Implementation map | [REFERENCE_TRAVELPLAN.md](../REFERENCE_TRAVELPLAN.md) |
| Schema | R06 + `.grok/guides/DEMO_OUTPUT_SCHEMA.md` |
| Non-travel changes | [DOMAIN_CUSTOMIZATION.md](../DOMAIN_CUSTOMIZATION.md) |

---

## 6. Out of scope for this preset

- Settings wizard  
- Full chat history UI  
- Multi-tenant production auth  
