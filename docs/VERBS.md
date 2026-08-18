# Direct V2 verbs (no LLM)

**Status:** shipped in **0.3.0** · tag **`0.3.0-alpha`**.  
**Module:** `zeus_client.zeus.verbs`  
**Naming:** `run_<zeus_verb>` for each exposed verb.

## Exposed vs not

| | Verbs |
|--|--------|
| **Exposed** | `describe`, `explain`, `get`, `find`, `set`, `order`, `enrich`, `project`, `traverse`, `search`, `analyze`, `return` |
| **Not exposed** | **`pipeline`** — multi-step DAGs stay on `run_agent` / low-level `dispatch_zeus_v2_verb` |

Constant: `EXPOSED_V2_VERBS` (tuple, pipeline stripped from `V2_DOCS_VERB_ORDER`).

## Public API

| Symbol | Role |
|--------|------|
| `run_verb(verb, args, *, zeus_url, bucket, scope, collection, zeus_headers\|zcfg, …)` | Generic POST |
| `run_verb_from_config(verb, args, cfg, *, sample=)` | Config triple + auth |
| `run_find` / `run_get` / `run_project` / `run_describe` / `run_explain` / `run_set` / `run_order` / `run_enrich` / `run_traverse` / `run_analyze` / `run_return` | Thin aliases |
| `run_search_verb` | Raw `search` body (avoids clashing with typeahead `run_search`) |
| `VerbResult` | `.status`, `.body`, `.req_id`, `.ok`, `.to_dict()` |

### search: two entrypoints

| Call | Use |
|------|-----|
| `run_search(query, …)` (`zeus.suggest`) | Typeahead: FTS + optional N1QL + find name/city merge |
| `run_search_verb({strategy, query_text, …})` / `run_verb("search", …)` | Single raw V2 search POST |

## Auth

Same as the rest of the client: pass minted `zeus_headers` **or** `zcfg` → `resolve_zeus_auth`. Default `X-Zeus-Mode: analytics` when unset.

## Hub Rewind (external hops)

Rewind plays a retained debug hop record for one `req_id` (`#/debug/rewind?req_id=`).
This client stamps `X-Zeus-Chat-Id` / `X-Zeus-Turn-Id` / `X-Zeus-Trace-Class`
on every `:8080` hop:

| Surface | `X-Zeus-Trace-Class` |
| --- | --- |
| Agent verb hops | `agent` |
| `/v2/session*` | `session` |
| Typeahead `search` | `direct.interactive` |
| Direct `rt.data.*` | `direct.read` |

Open the **tool** hop (`find`/`search`/`project`), never `POST /v2/session/{id}/turn`.
Pipeline hops are often edge-only in Rewind (Zeus does not `[redacted]`).
`X-Zeus-Trace: 1` is opt-in via `ClientSettings.force_trace` / `ZEUS_CLIENT_FORCE_TRACE`.
Never reuse `X-Zeus-Req-Id` across hops.

## E2E debug gather

Agent turns expose the nine gather fields on `TurnResult.debug` so integrators
do not need Hub Detective. See `docs/DEBUG_GATHER.md`.

## URL routing (via dispatch)

| Verb class | Path |
|------------|------|
| Bare (`explain`, `return`) | `POST /v2/{verb}` |
| Scope (`describe`, `analyze`) | `POST /v2/{bucket}/{scope}/{verb}` |
| Collection (rest) | `POST /v2/{bucket}/{scope}/{collection}/{verb}` |
| `pipeline` | **rejected** by `run_verb` |

## Example

```python
from zeus_client import ZeusClient, run_find, run_verb

async with ZeusClient():
    r = await run_find(
        {"entity_type": "Business", "where": {"city": "Largo"}, "limit": 8},
        zeus_url=zcfg["url"],
        bucket="yelp-data",
        scope="_default",
        zcfg=zcfg,
    )
    if r.ok:
        print(r.body)

    # pipeline is intentionally blocked:
    bad = await run_verb("pipeline", {"steps": []}, zeus_url=…, bucket=…, scope=…)
    assert not bad.ok and "not exposed" in bad.error
```

## Tests

```bash
pytest tests/test_zeus_verbs.py tests/test_smoke_imports.py -q
```
