# Prerequisites

**Status**: Draft  
**Related**: [CONFIG.md](CONFIG.md), [CATALOGS_AND_CONTRACTS.md](CATALOGS_AND_CONTRACTS.md)

---

## 1. Readiness matrix

| Dependency | What “ready” means |
|------------|-------------------|
| Zeus Engine | URL reachable; auth mode works |
| Sample data | Target bucket/scope/collection loaded (e.g. `travel-sample/_default`) |
| Contracts | `scope_contracts` mode keys match catalog modes (recommended) |
| LLM | OpenAI-compatible `base_url` + `api_key` + model list |
| Python | `>=3.11` |
| Layout | Sibling `zeus_client_python` for editable installs **or** published wheel |
| Docker | Optional; host networking understood |

---

## 2. Zeus readiness

<!-- TODO: health check steps, auth_mode options, scope credentials -->

- Base URL (host vs Docker)
- `auth_mode`: `none` | `basic` | `bearer` | `session`
- Durable sessions: `/v2/session*` on current engines

---

## 3. Sample data

<!-- TODO: how to confirm travel-sample / other samples loaded -->

| Sample | Typical mode | Notes |
|--------|--------------|--------|
| `travel-sample` | `travel_booking` | TravelPlan reference |
| Other | per domain | See [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md) |

---

## 4. LLM provider

<!-- TODO: xAI / OpenAI examples -->

Any OpenAI-compatible chat completions endpoint.

---

## 5. Monorepo layout

```text
koten-ai/
├── zeus_client_python/     # library
└── demo_<domain>/          # this demo app
```

`pyproject.toml` path dep example: `kotenai-zeus-client @ file:../zeus_client_python`

---

## 6. Docker networking

| Where Zeus runs | App in Docker should use |
|-----------------|--------------------------|
| Host machine | `http://host.docker.internal:8080` (typical) |
| Same compose network | service DNS name |
| Remote | public/private URL |

**Never** point the container at `localhost:8080` expecting the host Zeus.

---

## 7. Operator inputs checklist

Copy from [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) §3 and fill before scaffolding.
