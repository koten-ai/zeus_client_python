---
description: Demo Builder Kit — build vertical Zeus demos with kotenai-zeus-client
---

# Demo Builder Kit

**Status**: Active (ported)  
**Kit version**: 0.1.0  
**Date**: 2026-07-15  
**Package**: [`kotenai-zeus-client`](https://github.com/koten-ai/zeus_client_python)

AI-executable documentation to build vertical demos like **TravelPlan** (`demo_travel_sample`) on top of this library.

{% hint style="info" %}
**Primary home:** this tree (`docs/demo-builder/` in `zeus_client_python`).  
**GitBook:** site section **Demo** → variant **Python** (space path `demo/python`).  
**Reference app:** monorepo sibling `demo_travel_sample` or [TravelPlan README](https://github.com/koten-ai/demo_travel_sample) when published.
{% endhint %}

## Who this is for

| Audience | Start here |
|----------|------------|
| **Coding agents** | [AGENTS.md](AGENTS.md) → [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) → [ACCEPTANCE.md](ACCEPTANCE.md) |
| **Human integrators** | [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) → [SCAFFOLD.md](SCAFFOLD.md) → [RECIPES.md](RECIPES.md) |
| **Product owners** | [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) (success criteria + operator inputs) |

## Reading order

### AI agents (execute in order)

1. [AGENTS.md](AGENTS.md) — constraints and mission  
2. [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) — phases 0–10  
3. [PREREQUISITES.md](PREREQUISITES.md) — environment readiness  
4. [SCAFFOLD.md](SCAFFOLD.md) + [templates/](templates/)  
5. [CONFIG.md](CONFIG.md) + [RECIPES.md](RECIPES.md)  
6. [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md) (if not pure travel)  
7. [API_CONTRACT.md](API_CONTRACT.md) + [UI_CONTRACT.md](UI_CONTRACT.md) + [TRACE_PANEL.md](TRACE_PANEL.md)  
8. [ACCEPTANCE.md](ACCEPTANCE.md) — definition of done  

### Humans (understand then build)

1. [ARCHITECTURE.md](ARCHITECTURE.md)  
2. [REFERENCE_TRAVELPLAN.md](REFERENCE_TRAVELPLAN.md)  
3. [RECIPES.md](RECIPES.md) + [ANTI_EXAMPLES.md](ANTI_EXAMPLES.md)  
4. [presets/travel.md](presets/travel.md)  

## Document index

| Doc | Purpose |
|-----|---------|
| [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) | Entrypoint: intent, inputs, build order |
| [AGENTS.md](AGENTS.md) | Drop-in instructions for coding agents |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers, sequence, module map |
| [PREREQUISITES.md](PREREQUISITES.md) | Zeus, sample, LLM, Docker, monorepo |
| [CONFIG.md](CONFIG.md) | **Active** — annotated config + env |
| [RECIPES.md](RECIPES.md) | **Active** — R01–R12 + FastAPI R02b |
| [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md) | Parameterize mode/sample/schema/UI |
| [SCAFFOLD.md](SCAFFOLD.md) | File tree, pyproject, Docker |
| [API_CONTRACT.md](API_CONTRACT.md) | **Active** — exact TravelPlan HTTP schemas |
| [UI_CONTRACT.md](UI_CONTRACT.md) | Frontend stack + JSON fields |
| [CATALOGS_AND_CONTRACTS.md](CATALOGS_AND_CONTRACTS.md) | chat_request sync checklist |
| [TRACE_PANEL.md](TRACE_PANEL.md) | Vendored chat-trace embed |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Tests, smoke, troubleshooting |
| [REFERENCE_TRAVELPLAN.md](REFERENCE_TRAVELPLAN.md) | Annotated map → `demo_travel_sample` |
| [ANTI_EXAMPLES.md](ANTI_EXAMPLES.md) | Common failure modes |
| [presets/travel.md](presets/travel.md) | Travel vertical preset (v1 only) |

## Decisions (v1)

| Topic | Choice |
|-------|--------|
| Web frameworks | Flask **and** FastAPI |
| Trace panel | **Vendored JS** default; CDN optional note |
| Domain presets | Travel + customization only |
| GitBook | Site section **Demo** → variant **Python** (other langs later) |

## Compatibility

| Component | Notes |
|-----------|--------|
| `kotenai-zeus-client` | This repository |
| Zeus Engine | V2 tools/session APIs preferred |
| Reference demo | Sibling monorepo app `demo_travel_sample` (TravelPlan) |

## Related

- Library README: [../../README.md](../../README.md)  
- Minimal agent: [../../examples/minimal_agent.py](../../examples/minimal_agent.py)  
- GitBook SDK docs: Zeus Client → Python (Getting started / Integration tips)  
