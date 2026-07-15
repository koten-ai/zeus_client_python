# Project scaffold

**Status**: Draft  
**Related**: [templates/](templates/), [BUILDING_A_DEMO.md](BUILDING_A_DEMO.md) Phase 1

---

## 1. Target file tree

```text
demo_<domain>/
├── src/<package>/
│   ├── __init__.py          # calls configure_zeus_client()
│   ├── __main__.py
│   ├── app.py               # Flask factory or FastAPI app
│   ├── search.py
│   ├── async_runner.py      # Flask path; FastAPI may use lifespan instead
│   ├── zeus_config.py
│   ├── chat_store.py
│   ├── output_schema.py
│   ├── results_parser.py
│   ├── answer_parser.py
│   ├── templates/
│   └── static/              # includes vendored zeus_client_chat_trace.js
├── data/
│   └── chat_requests/
├── tests/
├── scripts/                 # optional verify_config.py
├── config.example.json
├── config.json              # gitignored
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 2. Packaging

<!-- TODO: package-data for templates/static; entry points -->

See [templates/pyproject.toml.snippet](templates/pyproject.toml.snippet).

Dependencies (minimum):

- `kotenai-zeus-client` (path or index)
- Web: `flask` and/or `fastapi` + `uvicorn`
- `httpx`

---

## 3. Docker

- Build context: monorepo parent when installing sibling client
- Env: `ZEUS_CLIENT_CONFIG_DIR`, `ZEUS_CHAT_REQUESTS_DIR`, `ZEUS_URL`
- See [templates/Dockerfile.snippet](templates/Dockerfile.snippet)

---

## 4. Framework choice

| Choice | Scaffold notes |
|--------|----------------|
| Flask | Include `async_runner.py` (R02); sync route handlers |
| FastAPI | Lifespan hooks (R02b); async route handlers; may omit thread loop |

TravelPlan reference is **Flask**.

---

## 5. Bootstrap commands

```bash
cp config.example.json config.json
# edit keys
pip install -e ".[dev]"
python -m <package>
# or
docker compose up --build
```

<!-- TODO: Fill package name placeholders -->
