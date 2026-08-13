# `chat_requests/V2/` — V2 verb-shaped chat-request snapshots (standardized 5TH contract shape)

This folder (the middle-man copy of Zeus `ai/V2/`) holds the **V2**
OpenAI-compatible request templates, one per mode, plus the
default-mode alias. As of the 5TH contract work, **V2 snapshots are
generated in the new standardized contract envelope** (`_format:
"zeus.chat_request.v2"`, with top-level `instructions`, `masq`,
`guidance`, `verbs`, `messages`, `metadata`, and a `contract` block for
stamping).

| File | Mode |
|---|---|
| `chat_request_v2.json` | alias of `chat_request_analytics_v2.json` |
| `chat_request_<mode>_v2.json` | per-mode V2 verb catalog (analytics, auto, code, custom, fraud, open, private, regulated, research, tenant) |

The Python middle-man normalizer (`_normalize_chat_request_shape`) + the
`/api/server_contract_hash` proxy (which now prefers `/verify` for
standardized files) let you load these directly. The `load_chat_request`
path will promote `verbs` → `tools` and the system prompt (already
containing the "Verb Priority & Cost Model" block) will have the live
SCOPE BRIEF spliced on top.

They are generated from the Zeus side
(`internal/api/chat_request_gen.go` using
`BuildChatRequestV2Standardized`); copy with:

```bash
# after regenerating on the Zeus side
cp -r ../Zeus/ai/V2/. .
# or run the snapshot in Zeus and copy
```

**Do not hand-edit** — keep them in sync with the Zeus generator (or the
hand-maintained `demo/chat_request_prototype.json` example).

> The full human-facing V2 reference lives in the Zeus `../README.md`
> (and the per-mode system prompt inside the files). See the 5TH contract
> MASTER doc for the full story on `/verify`, stamping, hash exclusion
> for `guidance`, and using the stamped file as your on-disk catalog.
>
> **For end users and integrators:** Read the top-level
> [`../CHAT_REQUEST_GUIDE.md`](../CHAT_REQUEST_GUIDE.md) — it explains in plain
> language what chat_request files do, what you must never change, where it is
> safe to customize (debug, business logic, optimal paths), how to get the
> live MINI-SCHEMA, and why contracts matter.

> The full human-facing V2 reference (verbs, routes, FK joins, Capabilities
> & cost model, Execution-style block) lives in [`../README.md`](../README.md).
> This file documents what is specific to the V2 snapshot folder, pipeline
> authoring (the most common LLM failure mode), and the transport layer.

## Pipeline authoring (read this if pipelines 400)

Admin chat and the Python middle-man both send the V2 catalog from these
snapshots. The `pipeline` verb is powerful but strict — three rejection
codes show up constantly when the model authors a DAG incorrectly:

| Code | Cause | Fix |
|------|-------|-----|
| `PIPELINE_STEP_MISSING_AS` | Step has no `as` binding name | Add unique `as` on **every** step |
| `PIPELINE_UNKNOWN_RETURN` | `return[]` lists verb names (`"project"`, `"find"`) | `return[]` must list step **`as`** names |
| `PIPELINE_TOO_MANY_STEPS` | More than 8 steps | Compress with FK joins or fewer steps |

### Required shape

Every pipeline step is an object with at least:

```json
{"verb": "find", "as": "co_breweries", "...verb args..."}
```

- **`as`** — unique binding name for the step. Later steps reference
  `@co_breweries.ids` (identity alias) or `@co_breweries.node_ids`.
- **`return[]`** — optional list of which step results to include in the
  response. Names step `as` values, e.g. `["brewery_rows"]`, not verbs.
- **Cap** — `steps` array max length **8** (enforced in preflight and in
  the `pipeline` tool schema `maxItems: 8`).

### Anti-pattern: per-parent fan-out

**Wrong** (11 steps — blows the cap):

```
project(breweries) → find(beers for brewery 1) → find(beers for brewery 2) → …
→ project(beers 1) → project(beers 2) → …
```

**Right** — compress with FK joins or shared child reads:

1. **Parent + related fields on the same row** — one-hop FK join in
   `project` / `enrich`: `fields: ["name", "brewery_id.name", "brewery_id.city"]`
   (use the MINI-SCHEMA `entity_fk` field name, not the target type).
2. **Hydrate a parent list** — canonical 2-step:

```json
{
  "steps": [
    {
      "verb": "find",
      "as": "co",
      "entity_type": "Brewery",
      "where": {"state": "Colorado"},
      "return": "ids",
      "limit": 20
    },
    {
      "verb": "project",
      "as": "rows",
      "ids": "@co.ids",
      "fields": ["name", "city", "description"]
    }
  ],
  "return": ["rows"]
}
```

3. **Top-N parent with child columns** — `find`(return:`ids`) → `project` with
   dotted FK fields (see system prompt "Canonical top-N X with related Y fields").

### Bindings cheat-sheet

| Need | Bind |
|------|------|
| Id list for `project` / `get` / `order` | `@<as>.ids` |
| Typed node ids | `@<as>.node_ids` |
| FK values for child `where` (entity_fk) | `@<as>.items[*].doc_key` — **not** `@<as>.ids` |
| Whole step rejected | bare `@<as>` (map envelope, not an array) |

Empty `@<as>.ids` resolves to `[]` — `project`/`order` accept it and return zero
rows instead of `project: ids must be an array`. For parent→child beer lookups,
`brewery_id` stores doc keys; binding `@breweries.ids` (node ids) returns 0 beers.

When uncertain, validate first: `POST /v2/{bucket}/{scope}/{collection}/pipeline/plan`
(same body as execute; returns preflight errors without running handlers).

## `walk_path` authoring (`traverse` shape=walk_path)

Admin chat trace `req_id=25ef66c2-…` ("How many beers does each Colorado
brewery produce? use transverse and walk_path") is the reference failure:
**~23.6s / 6 LLM rounds** of schema ping-pong, zero valid executions. The
compiler and data were fine; the model authored the wrong shapes.

Full design notes: [`docs/work/4TH/EDGE_TO_EDGE_IDEA.md` §9](../../docs/work/4TH/EDGE_TO_EDGE_IDEA.md).

### Common mistakes

| Mistake | Symptom | Fix |
|--------|---------|-----|
| Top-level `"inverse"` | `unknown field "inverse"` | `path: [{"inverse":"Beer.brewery_id"}]` only |
| Pipeline `find` → `traverse(from:@step, walk_path:{path})` | `walk_path.from` missing / incomplete | Put seed in `walk_path.from` — traverse `from` is **not** merged today |
| `aggregate.group_by: "brewery.name"` | `bad_request` on cross-alias group | Terminal-local: `group_by: "brewery_id"` on Beer; hydrate names separately |
| Repeated `find` + `limit: 20` | Under-count parents (20 vs 57 CO breweries) | One `walk_path.from.where` seeds all parents; drop `limit` when you need full cardinality |

### Canonical ✅ — Colorado brewery beer counts (one call)

Prefer **one direct `traverse`**, not a pipeline:

```json
{
  "shape": "walk_path",
  "walk_path": {
    "from": {
      "entity_type": "Brewery",
      "where": { "state": "Colorado" }
    },
    "path": [{ "inverse": "Beer.brewery_id" }],
    "aggregate": {
      "group_by": "brewery_id",
      "count": "*",
      "as": "beer_count"
    }
  }
}
```

Live `beer-sample/_default`: **57 breweries**, **267 beers**, ~180ms.

To add brewery **names**, run a second `project` on brewery doc keys from the
aggregate rows — do not use `group_by: "brewery.name"` in the same call.

### Anti-pattern: pipeline seed + path only

**Wrong** (binding gap — `walk_path.from` never gets `@co.ids`):

```json
{
  "steps": [
    { "verb": "find", "as": "co", "entity_type": "Brewery",
      "where": { "state": "Colorado" }, "return": "ids" },
    { "verb": "traverse", "as": "counts",
      "shape": "walk_path", "from": "@co.ids",
      "walk_path": { "path": [{ "inverse": "Beer.brewery_id" }],
        "aggregate": { "group_by": "brewery_id", "count": "*", "as": "beer_count" } } }
  ],
  "return": ["counts"]
}
```

**Right** — seed inside `walk_path.from` (see canonical example above), or
until the executor merges bindings, use `walk_path.from.src_keys` explicitly if
you already hold doc keys from a prior step.

### Support labels (beer-sample)

| Question | Status |
|----------|--------|
| "Where is 21A IPA brewed?" | ✅ `from:{Beer,doc_key}`, `path:["brewery_id"]` |
| "List beers by Stone Brewing" | ✅ / ⚠️ inverse from Brewery doc_key |
| "How many beers per Colorado brewery?" | ✅ aggregate `group_by: brewery_id` after inverse hop |
| "Beers from Belgian breweries" | 🚫 naive forward terminal projection — seed Brewery/Country, inverse to Beer |

### `find` args in pipelines

- `return` must be exactly `"rows"`, `"ids"`, `"count"`, or `"selectivity"` —
  valid JSON string, no extra quotes (`"\"ids"` 400s).
- `order_by` for metadata fields: `"field:<name>"` (e.g. `"field:ibu"`); bare
  field names like `"name"` are normalized server-side to `"field:name"`.

## Prompt caching (transport layer — NOT in these snapshots)

Prompt caching is **not** something baked into the system prompt or the
snapshot JSON. It is handled by the Python middle-man
([`Zeus_Python/app.py`](../../../Zeus_Python/app.py)) at request time,
because caching is a property of the HTTP call, not the prompt text.

How it works:

- **Automatic on prefix match.** Every major provider we ship (xAI,
  OpenAI, Gemini, DeepSeek) caches the longest *identical prefix* of the
  request. Our prefix is the large static block we always send first and
  never mutate: `systemPromptV2` (~24k chars) + the tool catalog. Across
  the multi-round agent loop and across turns of the same chat, that
  prefix is reused and billed at the reduced cached rate (xAI: e.g.
  ~$0.05–0.75 / 1M cached vs full input rate).
- **Routing key keeps the hit rate high.** The cache is best-effort —
  eviction and server routing can cause misses. The middle-man feeds a
  stable conversation id (`conv_id = chat_id`) so a conversation stays
  pinned to the same cache server:
  - **xAI / Grok** → `x-grok-conv-id` HTTP header.
  - **OpenAI** → `prompt_cache_key` body field.
  - **Other OpenAI-compatible providers** → nothing; they cache on
    prefix match automatically.
  See `cache_hints()` in `app.py`.
- **Visibility.** Each round records `cached_tokens` (read from
  `usage.prompt_tokens_details.cached_tokens`) in the trace
  (`ai_responses[].cached_tokens`), and a per-turn note states whether
  cache hints were sent or the provider caches automatically. If
  `cached_tokens` is consistently 0, the prefix is changing between
  rounds (or the conv id isn't stable).

### Why we did NOT trim the prompt to "go faster"

Caching makes the system prompt's *size* nearly free after the first
round, so trimming it would mostly sacrifice accuracy (the SCOPE BRIEF /
MINI-SCHEMA / WALK_PATHS / FK / pipeline authoring guidance that keep
answers correct) for a negligible latency win. Caching is the right lever;
trimming is not.

## Standardized contract prototype (new V2 shape)

A copy of the prototype illustrating the new standardized `chat_request` document shape (the one used for `/verify` + `/contract` stamping, with `instructions` / `masq` / `guidance` separation etc.) is included here for middle-man testing:

- `chat_request_prototype_v2.json` (top level — will appear in the Catalog UI as V2 mode "prototype")
- `demo/chat_request_prototype.json` (kept in sync with the source tree under Zeus/ai/V2/demo/)

This file (and all the regenerated `chat_request_*_v2.json`) use the full 5TH envelope (`_format: "zeus.chat_request.v2"`, `contract` with hash, `instructions`, `masq`, `guidance` (advisory, hash-excluded), `verbs`, `messages`, `metadata`).

**In the UI Catalog you will now see a bright red badge + warning box** if you Load anything that is *not* a proper V2 standardized contract shape (V1 files, old flat V2, or incomplete snapshots). The message is: it may still return correct data for the current question, but you are outside the contract/MASQ/hot-path guarantees and drift detection.

See the 5TH contract MASTER for the full story. The middle-man now strongly prefers the stamped `contract.hash` from the server or from a pre-stamped file.

See the matching file and docs on the Zeus side:
`ai/V2/demo/chat_request_prototype.json` + the 5TH contract work items.

## Sync to the middle-man

After regenerating, copy both snapshot sets into the Python proxy:

```bash
cp ai/V2/*.json ../Zeus_Python/chat_requests/V2/
cp ai/V1/*.json ../Zeus_Python/chat_requests/V1/
```

(Only the `*.json` files are consumed by the middle-man; this `README.md`
stays in the Zeus repo.)