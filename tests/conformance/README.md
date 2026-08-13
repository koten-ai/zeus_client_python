# Offline conformance adapter (ZCP-21)

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
```

Report: `tests/conformance/last_report.json` (gitignored optional).

## Coverage

| Level | Driver |
| --- | --- |
| L0 catalog / envelope | Design fixtures via V2 path helpers |
| L1 single tool return | Real `run_agent_turn` + scripted LLM/Zeus from wire |
| L2 policy / layer A / G2 / triggers / rules | V2 domain |
| L2 settings product default | Fixture profiles (`ai_process_result=false` product) — package Hub default stays True |
| DT smooth_* | assert_only slim + rewind companions |
| DT fail_zeus | wire 409 mock — no forged hash |
| DT fail_client missing mini | V2 detective builder |

## Blocked / residual

If design repo missing: adapter errors at resolve. Kit rewind full agent re-run is not claimed; companions + assert_only satisfy `required_rewind` offline.
