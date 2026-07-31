# base-5 Client control plane (0.2.x)

**Status:** base-5 floor in **0.2.0**; **`ai_process_result`** (ZC-WISH-044) in **0.2.1**; cheap path no second LLM hop + **fast suggest** in **0.2.2**.  
**SoT packs:** [zeus_chat_request](https://github.com/koten-ai/zeus_chat_request) `v2/base/base-5.3/` (wire = base-5).  
**Pin:** production `CURRENT.json` remains **base-1** — do not invent stamps; Hub stamp only.

## What 0.2.0 adds

| Capability | API |
| --- | --- |
| Load by `base_id` | `load_base_catalog(base_id=..., mode=..., search_dirs=...)` · `run_agent(..., base_id=...)` |
| Settings bag + rules merge/freeze | `ClientSettings`, `prepare_settings`, `merge_rules` |
| Default jailbreak named rules | always merged unless `override_defaults=True` |
| Prompt inject (hash-excluded) | company_context, rules{}, output_request, session meta |
| Layer A parse | `parse_layer_a` — required four + object triggers + `app_output` |
| Dual-read array triggers | `allow_array_triggers=True` in 0.2.x only — remove in next minor |
| Policy table | every structured/settings turn → `policy`, `ui_text`, `flags` |
| Dual jailbreak scores | model `jail_break_attempt` **and** `hooks_jailbreak_score` (never same field) |
| G1 UI vs artifacts | `ui` / `ui_text` vs `artifacts` (G2 never chat UI) |
| AI on Zeus result | `ClientSettings.ai_process_result` (default **`true`**, Hub Debug parity) |

## Minimal example

```python
from pathlib import Path
from zeus_client import (
    ClientSettings,
    run_agent,
    load_base_catalog,
)

# Offline spike catalog (unstamped candidate — not production)
dirs = [Path("tests/fixtures/base-5.3")]
settings = ClientSettings(
    company_context="We are a craft beer guide.",
    rules={"loyalty": "Apply loyalty only from tool data."},
    output_request={
        "app": {
            "fields": {
                "offer_code": {
                    "type": "string",
                    "description": "Promo code if user presented one, else empty",
                }
            }
        }
    },
    locale="en-US",
    channel="web",
    # Hub default on; set False for cheap path (AI → Zeus → UI, no insight hop)
    ai_process_result=True,
)

answer, trace, history, session, structured = await run_agent(
    ...,
    structured=True,
    base_id="base-5.3",
    base_catalog_dirs=dirs,
    settings=settings,
)
print(structured.policy, structured.ui_text, structured.flags)
print(structured.artifacts)  # admin / metrics — not end-user chrome
```

## `ai_process_result` (ZC-WISH-044)

| Value | Loop after Zeus tool data |
| --- | --- |
| **`true` (package default)** | Insight path — after terminating `return` / pipeline `turn_complete`, one **no-tools** synthesis turn narrates tool JSON (mirrors Zeus Hub Debug “AI on Zeus result”). Non-terminating tools continue the open multi-round loop. |
| **`false`** | Cheap path — after tools with data, **no second LLM hop** (use pipeline/tool ``summary`` arg if present, else a static thin line; UI shows Zeus rows); after terminate, return the terminal summary immediately without an insight hop. |

```python
# Product / lab cheap path (show tables, skip second billable essay)
settings = ClientSettings(ai_process_result=False)
await run_agent(..., settings=settings)
```

Still honors `max_rounds`. When insight is on and `max_rounds < 2`, Client raises the floor to 2.

## Hash safety

Injects splice **after** `## SCOPE BRIEF` / `## MINI-SCHEMA` only.  
`compute_contract_hash` before/after inject must match when the brief marker is present.

## Compatibility

- Legacy `*_v2.json` load path unchanged when `base_id` is omitted.
- `guidance.injections.business_logic` list inject still works (ZC-36 lint path).
- Prefer named `settings.rules` for new base-5 work.
- base-6 soft `hints.*` inject is **not** in 0.2.0 (ZC-WISH-040 later).
- Wishlist/ROADMAP product default for `ai_process_result` is often **false**; this package defaults **true** to match Hub Debug. Set `false` explicitly for product cheap cost.

## Tests

```bash
pytest tests/test_base_catalog_load.py tests/test_layer_a.py \
  tests/test_settings_rules_merge.py tests/test_prompt_inject_hash_stable.py \
  tests/test_policy_table.py tests/test_agent_loop.py tests/test_agent_tool_round.py -q
pytest -q
```
