# E2E debug gather (nine fields)

Integrators do **not** need Hub Detective. After `rt.agent.run_turn(...)`,
read `result.debug` (typed `DebugBundle`). Optional Hub URLs are links only.

## Nine fields

| # | Field | Where |
| --- | --- | --- |
| 1 | `chat_id` / `turn_id` / `session_id` | `debug.chat_id`, `debug.turn_id`, `debug.session_id` |
| 2 | `req_ids[]` + preferred + hop class | `debug.req_ids`, `debug.preferred_req_id`, `debug.hops[].name` / `path_class` |
| 3 | Target + Zeus URL + client version | `debug.target`, `debug.zeus_url`, `debug.client_version` |
| 4 | Catalog flags + tools/verbs + contract | `debug.catalog`, `debug.contract_status` |
| 5 | Inject proof | `debug.catalog.brief_sha12` / `mini_sha12` (slice, not whole system) |
| 6 | Hop table | `debug.hops[]` — verb, status, ms, error, url, snippet (≤2000), step_costs |
| 7 | Layer A + peeled answer | `result.answer` (peeled); compact bag on `debug.public_trace.layer_a` |
| 8 | Tokens | `debug.tokens` = `{prompt,completion,total,cached,extra,ok}` |
| 9 | Journal export | `rt.debug.export_journal(turn_id=result.debug.export_ref)` |

Ticket paste: `result.debug.detective["diagnosis"]["support_pack"]["markdown"]`.

## Session join (opt-in)

`enable_sessions=True` **and** an injected `SessionLifecycle` posts
`POST /v2/session/trace` with the **tool** hop `req_id` (never `/turn`).
Default `AgentAPI.run_turn(..., enable_sessions=False)` does not open `:8080`.

## Never

- Rewind `/v2/session/{id}/turn`
- Reuse `X-Zeus-Req-Id`
- Invent `contract_hash`
- Put G2 (`wish_i_knew`, jail scores) in `answer` or compact `layer_a`

See also `docs/VERBS.md` § Hub Rewind.
