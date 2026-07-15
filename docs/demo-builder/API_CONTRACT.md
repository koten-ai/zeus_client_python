# API contract

**Status**: Active (exact schemas from TravelPlan)  
**Sources**: `src/travel_planner/app.py`, `search.py`, `results_parser.py`, `answer_parser.py`, `zeus_client.trace.tool_order`, `zeus_client.agent.response`  
**Related**: [UI_CONTRACT.md](UI_CONTRACT.md), [RECIPES.md](RECIPES.md) R09, [templates/openapi-demo.yaml](templates/openapi-demo.yaml)

This document is the **machine contract** for demos that match TravelPlan’s HTTP surface. New demos should implement at least these three routes with the same JSON shapes so the UI and trace panel keep working.

---

## 1. Endpoints overview

| Method | Path | Content-Type | Purpose |
|--------|------|--------------|---------|
| `GET` | `/` | `text/html` | Search UI (Jinja); injects initial `toolOrder` |
| `POST` | `/api/search` | `application/json` | One agent turn |
| `GET` | `/api/tool-order` | `application/json` | Trace panel tool-name axes |

No auth on these routes in TravelPlan (demo-local).

---

## 2. `GET /`

### Response

- **200** HTML page  
- Server injects into the page:

```html
<script>
  window.ZeusTraceConfig = {
    toolOrder: { "v1": [...], "v2": [...] }
  };
</script>
<script src="/static/zeus_client_chat_trace.js" async></script>
```

`toolOrder` is produced by `build_tool_order(CHATS)` (same shape as §4).

Optional template vars: `build_version` (string from `config.json`).

---

## 3. `POST /api/search`

### 3.1 Request

**Headers**

```http
Content-Type: application/json
```

**Body**

```json
{
  "query": "warm beaches in Europe under $2000",
  "chat_id": "travel_a1b2c3d4e5f6"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|--------|
| `query` | string | **yes** | Trimmed; empty / whitespace → **400** |
| `chat_id` | string \| null | no | Omit or null to start a new chat; pass previous `chat_id` for multi-turn |

Missing body is treated as `{}` (`request.get_json(silent=True) or {}`).

**cURL**

```bash
curl -sS -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"tropical destinations with great food"}'
```

Follow-up:

```bash
curl -sS -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"cheaper options","chat_id":"travel_a1b2c3d4e5f6"}'
```

---

### 3.2 Success response — **200**

Top-level object returned by `search._search_async` (serialized as JSON). **All keys below are always present on success** (values may be empty string, `null`, `[]`, or `{}` depending on the turn).

```json
{
  "chat_id": "travel_a1b2c3d4e5f6",
  "query": "warm beaches in Europe under $2000",
  "answer": "Here are some great options…",
  "structured_answer": { },
  "structured_response": { },
  "results": [ ],
  "trace": { },
  "tool_order": { "v1": [], "v2": [] },
  "target": "travel-sample/_default/_default",
  "api_version": "v2",
  "mode": "travel_booking",
  "model": "grok-4-1-fast-non-reasoning",
  "provider": "xai",
  "zeus_connection": "default",
  "zeus_url": "http://host.docker.internal:8080",
  "session_id": "sess_…",
  "session_round": 2,
  "contract_status": "match"
}
```

#### Top-level field table

| Field | Type | Always | Description |
|-------|------|--------|-------------|
| `chat_id` | string | yes | Conversation id. Generated as `travel_` + 12 hex chars if request omitted `chat_id`. |
| `query` | string | yes | Original user query (unprefixed). |
| `answer` | string \| object | yes | LLM final answer (usually markdown string; may be dict if structured agent mode returns one). |
| `structured_answer` | object \| null | yes | Parsed markdown/JSON structure from answer parser, or `null` if unparseable. See §3.4. |
| `structured_response` | object | yes | `dataclasses.asdict(StructuredAgentResponse)`. See §3.5. |
| `results` | array of objects | yes | Destination **cards** for the UI. See §3.3. Max 20. |
| `trace` | object | yes | Agent execution trace from `run_agent` (opaque to UI cards; required by trace panel). See §3.6. |
| `tool_order` | object | yes | `{ "v1": string[], "v2": string[] }` from `build_tool_order(CHATS)`. Same as §4. |
| `target` | string | yes | `"{bucket}/{scope}/{collection}"` used for the turn. |
| `api_version` | string | yes | Normalized version, e.g. `"v2"`. |
| `mode` | string | yes | Agent mode / catalog key, e.g. `"travel_booking"`. |
| `model` | string | yes | Model id used for the turn. |
| `provider` | string | yes | Provider id derived from `llm_provider.label` first word (lowercased), else host of `base_url`, else `"default"`. Example: label `"xAI Grok"` → `"xai"`. |
| `zeus_connection` | string | yes | `zcfg.get("name")` or `"default"` (modern config often has no `name`). |
| `zeus_url` | string | yes | Resolved Zeus base URL (after `ZEUS_URL` override). |
| `session_id` | string | yes | Durable Zeus session id (may be `""` if sessions off / failed). From `session_meta` or prior chat state. |
| `session_round` | number | yes | Integer round for next durable-session turn (may be `0`). |
| `contract_status` | string \| null | yes | From session meta / chat, e.g. `"match"`, `"none"`, drift statuses, or `null`/omitted semantics via Python `None` → JSON `null`. |

**Note:** Success responses do **not** include an `error` field.

---

### 3.3 `results[]` — card schema

Produced by the result waterfall (R07):

1. `zeus_data_to_results(structured.zeus_data)`  
2. else `extract_destinations(trace)`  
3. else `structured_answer_to_results(structured_answer)`  

Each element is a **flat string map** (optional keys omitted when empty).

#### Required card fields (when a card is emitted)

| Field | Type | Notes |
|-------|------|--------|
| `name` | string | Non-empty; used as card title |
| `description` | string | May be `""` |
| `image` | string | URL or `""` |

#### Optional card fields

| Field | Type | Source |
|-------|------|--------|
| `location` | string | address / city,state,country composite |
| `address` | string | raw address |
| `city` | string | |
| `state` | string | |
| `country` | string | |
| `price` | string | price / price_range / rate |
| `url` | string | url / website / link |
| `area` | string | Travel-sample hotel `title` when distinct from `name` |

**Example**

```json
{
  "name": "Hôtel Example",
  "description": "Boutique stay near the river",
  "image": "https://example.com/photo.jpg",
  "location": "Paris, France",
  "address": "1 Rue Example",
  "city": "Paris",
  "country": "France",
  "price": "€120",
  "url": "https://example.com",
  "area": "4th arrondissement"
}
```

#### Frontend normalization (TravelPlan `app.js`)

The UI maps each card through `normalizeResult` and does **not** require extra API fields:

| UI field | From API |
|----------|----------|
| `title` | `name` \|\| `title` |
| `location` | `location` \|\| `address` |
| `image` | `image` / `image_url` / … if looks like image URL; else placeholder SVG |
| `price` | parsed number from `price` string |
| `priceLabel` | raw `price` string |
| `url` | `url` \|\| `website` \|\| `link` |
| `id` | **client-only** index+1 (not from API) |

**Contract for new demos:** emit at least `name`, `description`, `image` (string) on each result for drop-in UI compatibility.

---

### 3.4 `structured_answer` schema

Type: `object | null`.

Produced by `parse_markdown_answer(answer)`.

#### When `null`

- Empty / non-string answer with no structure  
- Markdown with no recognizable sections, numbered items, or fenced JSON  

#### Variant A — fenced JSON in answer

If the answer contains ` ```json { ... } ``` `, the parsed object is returned as-is (any JSON object shape).

#### Variant B — numbered list only

```json
{
  "items": [
    {
      "name": "Santorini",
      "description": "…",
      "location": "Greece",
      "price": "…"
    }
  ],
  "context": "optional intro paragraph",
  "tip": "optional tip text",
  "follow_up": "Would you like …?"
}
```

| Field | Type | When present |
|-------|------|----------------|
| `items` | array of objects | Numbered `1. **Name**` blocks |
| `context` | string | Long intro before first heading |
| `tip` | string | `**Tip**: …` |
| `follow_up` | string | Trailing “Would you like…?” |

Item objects: at least `name`; other keys from `- **Field**: value` bullets (aliases: location, address, description, image, price, rating, duration, url, directions).

#### Variant C — markdown headings (airports / sections)

```json
{
  "airports": [
    {
      "name": "CDG (Paris)",
      "section": "optional subtitle after dash",
      "hotels": [
        { "name": "Hotel A", "description": "…", "price": "…" }
      ]
    }
  ],
  "sections": [
    {
      "name": "Top matching hotels",
      "section": "optional",
      "items": [
        { "name": "Hotel B", "description": "…" }
      ]
    }
  ],
  "context": "…",
  "tip": "…",
  "follow_up": "…"
}
```

| Field | Type | When |
|-------|------|------|
| `airports` | array | Heading looks like airport (name contains airport tokens / parens) → children as `hotels` |
| `sections` | array | Other headings → children as `items` |
| `context` / `tip` / `follow_up` | string | Same extractors as Variant B |

**UI usage:** prefers `structured_answer.context` or `.tip` for the summary strip when present.

---

### 3.5 `structured_response` schema

Serialization of `zeus_client.agent.response.StructuredAgentResponse` via `dataclasses.asdict`:

```json
{
  "answer": "…",
  "zeus_data": [
    {
      "entity_type": "Hotel",
      "id": "…",
      "doc_key": "…",
      "name": "…",
      "description": "…"
    }
  ],
  "decomposition": null,
  "return_payload": null,
  "entity_type": "Hotel",
  "source_tool": "search",
  "warnings": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `answer` | string | Natural-language answer (mirrors top-level `answer` in structured mode) |
| `zeus_data` | array of objects | Schema-filtered rows (`output_schema` / mini-schema). Keys vary by entity; reserved: `id`, `doc_key`, `entity_type`. |
| `decomposition` | object \| null | Query understanding payload when present |
| `return_payload` | object \| null | Args from last `return` / `return_result` step |
| `entity_type` | string \| null | Dominant entity type for the turn |
| `source_tool` | string \| null | Data tool that produced rows (`search`, `find`, `pipeline`, …) |
| `warnings` | string[] | Dropped fields / filter notes |

TravelPlan maps `zeus_data` → `results` via `zeus_data_to_results` first in the waterfall.

---

### 3.6 `trace` schema (summary)

`trace` is an **opaque object** owned by `kotenai-zeus-client`. The demo must pass it through to the client for the chat-trace panel. Do not require UI features to depend on internal keys beyond what the vendored panel reads.

Common keys observed from the agent loop (non-exhaustive; may grow):

| Key | Type | Role |
|-----|------|------|
| `rounds` | number | LLM rounds executed |
| `steps` | array | Mixed step records (`llm`, tools, errors, …) |
| `tool_calls` | array | Per-tool records (`name`, `result_json`, `result_text`, …) |
| `spans` | array | Timing spans (`name`, `cls`, `at`, `ms`) |
| `notes` | string[] | Human-readable audit / session notes |
| `session` | object | `{ id, round, contract_status, enabled, error? }` |
| `ai_requests` / `ai_responses` | array | LLM payload logs |
| `runtime_basic_chat_audit` | object | Optional runtime audit block |

**Contract rule for demos:** always include the full `trace` object from `run_agent` on success; do not strip keys.

---

### 3.7 Error responses

TravelPlan returns JSON `{ "error": "<message>" }` with status based on cause.

| HTTP | Condition | Example `error` |
|------|-----------|-----------------|
| **400** | Empty / whitespace `query` | `"empty query"` |
| **400** | `ValueError` from search (config) | `"no Zeus URL configured (edit config.json)"` |
| **400** | | `"llm_provider has no api_key set (edit config.json)"` |
| **400** | Other `ValueError` / `RuntimeError` | message string |
| **502** | `httpx.HTTPError` or error string containing `"network error"` | `"network error: …"` |

```json
{
  "error": "empty query"
}
```

```json
{
  "error": "network error: [Errno 111] Connection refused"
}
```

**Not used on success:** top-level `error`.  
**Client check (TravelPlan):** `if (!res.ok || data.error)`.

---

## 4. `GET /api/tool-order`

### Request

No body. No query params.

### Response — **200**

```json
{
  "v1": ["search", "get", "…"],
  "v2": [
    "describe",
    "explain",
    "get",
    "find",
    "set",
    "order",
    "enrich",
    "project",
    "traverse",
    "pipeline",
    "search",
    "analyze",
    "return"
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `v1` | string[] | First-seen V1 tool names from in-memory `CHATS` traces (may be empty at cold start) |
| `v2` | string[] | Canonical V2 verb order from `v2_tool_order()` — default list above when Zeus V2 docs dir is unavailable |

Implementation:

```python
from zeus_client import build_tool_order
return jsonify(build_tool_order(CHATS))
```

Also returned **inline** on every successful search as `tool_order` (same shape).

---

## 5. Multi-turn contract

| Step | Client | Server |
|------|--------|--------|
| First search | omit `chat_id` | allocate `chat_id`, return it |
| Follow-up | send same `chat_id` | load `turns`, `zeus_session_id`, `zeus_round`; pass into `run_agent` |
| Response | store `chat_id` | update store + JSONL; return new `session_id` / `session_round` |

Chat id format (TravelPlan): `travel_` + `uuid.uuid4().hex[:12]` (e.g. `travel_a1b2c3d4e5f6`). Other demos may change the prefix but must keep a stable opaque string.

---

## 6. JSON Schema (success body)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://koten.ai/schemas/demo-api-search-success.json",
  "title": "DemoSearchSuccess",
  "type": "object",
  "required": [
    "chat_id",
    "query",
    "answer",
    "structured_answer",
    "structured_response",
    "results",
    "trace",
    "tool_order",
    "target",
    "api_version",
    "mode",
    "model",
    "provider",
    "zeus_connection",
    "zeus_url",
    "session_id",
    "session_round",
    "contract_status"
  ],
  "properties": {
    "chat_id": { "type": "string", "minLength": 1 },
    "query": { "type": "string" },
    "answer": {},
    "structured_answer": {
      "anyOf": [{ "type": "object" }, { "type": "null" }]
    },
    "structured_response": {
      "type": "object",
      "required": ["answer", "zeus_data", "warnings"],
      "properties": {
        "answer": { "type": "string" },
        "zeus_data": { "type": "array", "items": { "type": "object" } },
        "decomposition": { "anyOf": [{ "type": "object" }, { "type": "null" }] },
        "return_payload": { "anyOf": [{ "type": "object" }, { "type": "null" }] },
        "entity_type": { "anyOf": [{ "type": "string" }, { "type": "null" }] },
        "source_tool": { "anyOf": [{ "type": "string" }, { "type": "null" }] },
        "warnings": { "type": "array", "items": { "type": "string" } }
      }
    },
    "results": {
      "type": "array",
      "maxItems": 20,
      "items": {
        "type": "object",
        "required": ["name", "description", "image"],
        "properties": {
          "name": { "type": "string", "minLength": 1 },
          "description": { "type": "string" },
          "image": { "type": "string" },
          "location": { "type": "string" },
          "address": { "type": "string" },
          "city": { "type": "string" },
          "state": { "type": "string" },
          "country": { "type": "string" },
          "price": { "type": "string" },
          "url": { "type": "string" },
          "area": { "type": "string" }
        },
        "additionalProperties": { "type": "string" }
      }
    },
    "trace": { "type": "object" },
    "tool_order": {
      "type": "object",
      "required": ["v1", "v2"],
      "properties": {
        "v1": { "type": "array", "items": { "type": "string" } },
        "v2": { "type": "array", "items": { "type": "string" } }
      }
    },
    "target": { "type": "string" },
    "api_version": { "type": "string" },
    "mode": { "type": "string" },
    "model": { "type": "string" },
    "provider": { "type": "string" },
    "zeus_connection": { "type": "string" },
    "zeus_url": { "type": "string" },
    "session_id": { "type": "string" },
    "session_round": { "type": "number" },
    "contract_status": { "anyOf": [{ "type": "string" }, { "type": "null" }] }
  },
  "additionalProperties": true
}
```

Error body:

```json
{
  "type": "object",
  "required": ["error"],
  "properties": {
    "error": { "type": "string", "minLength": 1 }
  }
}
```

---

## 7. Compatibility checklist for new demos

- [ ] `POST /api/search` accepts `{ query, chat_id? }`  
- [ ] Empty query → **400** `{ "error": "empty query" }`  
- [ ] Success includes all top-level keys in §3.2 (or document deliberate omissions)  
- [ ] `results[]` items have `name`, `description`, `image`  
- [ ] `trace` is the full agent trace object  
- [ ] `tool_order` is `{ v1, v2 }` on search **and** `GET /api/tool-order`  
- [ ] Network failures → **502** with `error` containing `"network error"`  
- [ ] Config validation → **400** with descriptive `error`  
- [ ] Multi-turn: client can echo `chat_id`  

---

## 8. Related

| Doc / code | Role |
|------------|------|
| `src/travel_planner/app.py` | Route status codes |
| `src/travel_planner/search.py` | Success payload assembly |
| `src/travel_planner/results_parser.py` | Card field mapping |
| `src/travel_planner/answer_parser.py` | `structured_answer` variants |
| `src/travel_planner/static/app.js` | Client consumption |
| [RECIPES.md](RECIPES.md) R09 | Implementation recipe |
| [UI_CONTRACT.md](UI_CONTRACT.md) | UX surfaces |
| [templates/openapi-demo.yaml](templates/openapi-demo.yaml) | OpenAPI mirror |
