# Offline conformance adapter (ZCP-21 / CHECKLIST E)

**Suite pin:** `sdk_bootstrap.pins.json` → `suite.suite_version` + `design_repo_ref`  
**Contract:** `zeus_client_design/conformance/adapter/ADAPTER_CONTRACT.md`  
**Claim:** `candidate` until required cases green (never self-award `supported`)

## Run

```bash
# Design reference (pure-law) — optional baseline
python3 ../zeus_client_design/conformance/adapter/reference/run_suite.py

# V2 language adapter
.venv/bin/python tests/conformance/run_suite.py
.venv/bin/python tests/conformance/run_suite.py --report /tmp/v2-conformance.json
.venv/bin/pytest tests/conformance -q
make conformance
```

Report: `tests/conformance/last_report.json`. Sibling `zeus_client_design` is **required** (CI fails if the checkout is missing).

## Coverage

| Level | Driver |
| --- | --- |
| L0 catalog / envelope | Design fixtures via V2 catalog / envelope helpers |
| L1 single tool return | Walk of design `llm_script` (same algorithm as the kit reference). Product cheap-final after `search` would skip the scripted `return` hop, so this case does **not** claim `run_agent_turn`. The real loop is locked in `tests/unit/application/test_agent_turn.py`. |
| L1 force return | Real `run_agent_turn` + `force_return_rounds_left` |
| L2 policy / layer A / G2 / triggers / rules | V2 domain |
| L2 settings product default | Fixture production profile **and** `ClientSettings()` default `ai_process_result=false`; profile `hub` is True |
| DT smooth_* | slim export parse + rewind companions (`llm_script` + `zeus_responses`); `layer_a.required_four` from companion `return` args via `parse_layer_a` |
| DT fail_zeus | `run_agent_turn` + 409 hop; `error_class` from `tool_trail` / `error_class_for` |
| DT fail_client missing mini | `classify_mini_schema(get_mini_schema(...))` → `missing_mini_schema` |
| DT fail_llm | `parse_layer_a` + `decide_policy` on invalid terminate |
| DT fail_control_plane | `parse_layer_a` + empty/false triggers; data path still ok |

Handlers must not copy `case.expect` into observe.

## Blocked / residual

- Full ZF-WISH-003 agent re-run of Detective tapes is **not** claimed. Companions + slim `assert_only` satisfy kit-β `required_rewind` offline.
- Missing design repo is a **hard fail** (CHECKLIST E), not a skip.
