# base-5 Client control plane (0.2.0)

**Status:** shipped in package **0.2.0** on the `feat/base-5-client-floor` line.  
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

## Hash safety

Injects splice **after** `## SCOPE BRIEF` / `## MINI-SCHEMA` only.  
`compute_contract_hash` before/after inject must match when the brief marker is present.

## Compatibility

- Legacy `*_v2.json` load path unchanged when `base_id` is omitted.
- `guidance.injections.business_logic` list inject still works (ZC-36 lint path).
- Prefer named `settings.rules` for new base-5 work.
- base-6 soft `hints.*` inject is **not** in 0.2.0 (ZC-WISH-040 later).

## Tests

```bash
pytest tests/test_base_catalog_load.py tests/test_layer_a.py \
  tests/test_settings_rules_merge.py tests/test_prompt_inject_hash_stable.py \
  tests/test_policy_table.py -q
pytest -q
```
