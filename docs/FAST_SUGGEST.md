# Fast-tier search (typeahead)

**Status:** shipped in **0.3.0** (`zeus_client.zeus.suggest`). Tag **`0.3.0-alpha`**
for demo pin / trial (`run_search` naming + direct verbs).

## Naming

Public helpers follow **`run_<primary_zeus_verb>`**. This path's primary wire
verb is **`search`** (FTS), so:

| Preferred | Role |
|-----------|------|
| `run_search(...)` | Main entry — headers or `zcfg` auth |
| `run_search_from_config(q, cfg)` | Uses `samples` / `zeus` / `couchbase` |

Deprecated aliases `run_fast_suggest` / `run_fast_suggest_from_config` were **removed in the 2.0.0 GA cutover train** (ZCM-032 / ZCP-37). Use `run_search` / `run_search_from_config` only.

Supporting types stay product-shaped: `SuggestOptions`, `SuggestHit`, `SuggestResult`
(typeahead cards), plus `CouchbaseQueryConfig`.

## Goal

Google-like suggestions while the user types, against a Zeus scope
(e.g. `yelp-data/_default/_default`), **without** the LLM agent loop.

## Public API

| Symbol | Role |
|--------|------|
| `run_search(...)` | Main entry — headers or `zcfg` auth |
| `run_search_from_config(q, cfg)` | Uses `samples` / `zeus` / `couchbase` |
| `SuggestOptions` | limit, entity_type, FTS timeout, feature flags |
| `SuggestResult` / `SuggestHit` | Structured hits + `to_dict()` for JSON APIs |
| `CouchbaseQueryConfig` | Optional Query-service hydrate |

## Call graph

```text
query (len >= 2)
  ├─ POST /v2/{b}/{s}/{c}/search  {strategy:fts, query_text, entity_type, limit, timeout_ms}
  │     └─ result.src_keys
  │           └─ optional N1QL USE KEYS hydrate → card fields
  ├─ exact name path:  find → project
  └─ exact city path:  find → project
        └─ merge_hits (FTS order first, dedupe id/name)
```

Exact name/city paths may use a server-side multi-step composition when available;
integrators should prefer `run_search` rather than hand-authoring those hops.

## Auth

Same as the rest of the client: `resolve_zeus_auth` via `zcfg`, or pass
pre-minted `zeus_headers` (`X-Zeus-Session` / Bearer).

## Hydrate rules

| Do | Don't |
|----|--------|
| N1QL `USE KEYS` on FTS `src_keys` | `project`/`get` with `biz:` as node ids |
| `find`→`project` for exact name/city | `hybrid` as default typeahead |
| Soft-empty on errors (BFF HTTP 200) | Call `run_agent` per keystroke |

N1QL runs only when `couchbase=` is passed, or `COUCHBASE_QUERY_URL` is set
(or a non-`None` mapping). Pure Zeus deploys skip Query-service.

## Frontend contract (BFF)

```http
GET /api/suggest?q=sushi&limit=8
```

```json
{
  "query": "sushi",
  "results": [
    {
      "id": "biz:…",
      "name": "…",
      "subtitle": "★4.5 · Largo · Sushi",
      "city": "Largo",
      "stars": 4.5,
      "source": "zeus_fts+n1ql"
    }
  ],
  "count": 1,
  "source": "zeus_fts+n1ql_hydrate",
  "fast_tier": true,
  "ai_process_result": false
}
```

Debounce 250–300ms; min length 2; Enter without selection → agent search.

## Tests

```bash
pytest tests/test_zeus_suggest.py tests/test_smoke_imports.py -q
```

## Follow-ups

- Optional short client-side HTTP timeout override on dispatch (today FTS is capped by Zeus `timeout_ms`)
- Fold `get_by_keys` into V2 when Zeus exposes it, drop N1QL dependency
- ~~Remove deprecated `run_fast_suggest*` aliases~~ **done** (ZCP-37 / GA cutover)
