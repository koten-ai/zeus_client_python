# Integration recipes

**Status**: Active (fleshed from TravelPlan + `kotenai-zeus-client`)  
**Related**: [CONFIG.md](CONFIG.md), [templates/](templates/), [REFERENCE_TRAVELPLAN.md](REFERENCE_TRAVELPLAN.md)

Each recipe: **When** · **Code** · **Reference** · **Failures** · **Related**

TravelPlan package root: `src/travel_planner/`. Library package: `zeus_client`.

---

## Recipe index

| ID | Name | Primary reference |
|----|------|-------------------|
| R01 | Env before import | `zeus_config.py`, `__init__.py` |
| R02 | Background asyncio loop (Flask) | `async_runner.py` |
| R02b | Native async app (FastAPI) | library `ZeusClient` / lifespan |
| R03 | HTTP lifecycle | `async_runner.startup` / `shutdown` |
| R04 | Startup catalog sync | `async_runner._sync_chat_requests_on_startup` |
| R05 | Domain `run_agent` wrapper | `search.py` |
| R06 | `output_schema` allowlist | `output_schema.py` |
| R07 | Result waterfall | `search.py` + parsers |
| R08 | Multi-turn chat store + session IDs | `chat_store.py`, `search.py` |
| R09 | Minimal HTTP API (Flask) | `app.py` |
| R10 | Trace tool-order + vendored panel | `static/`, `templates/index.html` |
| R11 | Docker monorepo client install | `Dockerfile`, `docker-compose.yml` |
| R12 | Config verification script | `scripts/verify_config.py` |

---

## R01 — Env before import

**When**: Every app embedding `zeus_client`.

**Why**: `zeus_client.constants` binds `USER_CONFIG_DIR`, `CONFIG_PATH`, and chat-request dirs from env at import time. Setting env later is too late for those module-level values.

**Code** (TravelPlan pattern):

```python
# zeus_config.py
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # adjust to your layout

def configure_zeus_client() -> None:
    os.environ.setdefault("ZEUS_CLIENT_CONFIG_DIR", str(PROJECT_ROOT))
    os.environ.setdefault(
        "ZEUS_CHAT_REQUESTS_DIR",
        str(PROJECT_ROOT / "data" / "chat_requests"),
    )
    os.environ.setdefault("CHAT_LOG_PATH", str(PROJECT_ROOT / "data" / "chats.jsonl"))
```

```python
# package __init__.py — must run first
from my_package.zeus_config import configure_zeus_client

configure_zeus_client()
```

TravelPlan also calls `configure_zeus_client()` again inside `startup()` and `create_app()` as defense in depth.

**Optional (TravelPlan only)**: `patch_durable_session_v2_routes()` rewrites `/v1/session` → `/v2/session` for older baked client images. Upstream `zeus_client_python` already uses `/v2`; new demos on a current client can skip the shim.

**Reference**:

- `src/travel_planner/zeus_config.py`
- `src/travel_planner/__init__.py`
- `src/travel_planner/paths.py` (`PROJECT_ROOT = SRC_DIR.parent`)
- [templates/zeus_config.py](templates/zeus_config.py)

**Failures**:

| Symptom | Cause |
|---------|--------|
| Config loaded from `~/.config/zeus_client` | Env not set before import |
| Catalogs not found under `data/chat_requests` | `ZEUS_CHAT_REQUESTS_DIR` unset |
| Chat log in wrong place | `CHAT_LOG_PATH` unset |

**Related**: [CONFIG.md](CONFIG.md)

---

## R02 — Background asyncio loop (Flask / sync frameworks)

**When**: Sync WSGI (Flask) must call async `run_agent` / `httpx` client APIs.

**Why**: A single long-lived event loop in a daemon thread avoids `asyncio.run()` per request (which breaks shared HTTP client state and nested-loop issues).

**Code** (from `async_runner.py`):

```python
import asyncio
import threading

_loop: asyncio.AbstractEventLoop | None = None

def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is not None:
        return _loop
    loop = asyncio.new_event_loop()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=run, name="async-runner", daemon=True).start()
    _loop = loop
    return loop

def run_coro(coro, timeout: float = 600):
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
```

Sync entry for routes:

```python
# search.py
def run_search(query: str, chat_id: str | None = None) -> dict:
    try:
        return run_coro(_search_async(query, chat_id))
    except RuntimeError as e:
        return {"error": str(e)}
    except httpx.HTTPError as e:
        return {"error": f"network error: {e}"}
    except ValueError as e:
        return {"error": str(e)}
```

**Reference**: `src/travel_planner/async_runner.py`, [templates/async_runner.py](templates/async_runner.py)

**Failures**:

| Symptom | Fix |
|---------|-----|
| Hangs on search | Loop never started — call `startup()` / `_ensure_loop()` |
| Timeout after 600s | Long agent run; raise timeout or optimize prompts |
| Nested loop errors | Do not also call `asyncio.run` on the same thread |

**Related**: R03, R04, R05, R09

---

## R02b — Native async app (FastAPI)

**When**: FastAPI / ASGI with native `async def` routes.

**Why**: No background thread loop needed; reuse the server event loop. TravelPlan does **not** ship FastAPI — this recipe is the kit’s dual-framework path.

**Code** (pattern; adapt names):

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from zeus_client import ZeusClient, build_tool_order, close_http, init_http, load_config

from my_package.zeus_config import configure_zeus_client
# from my_package.search import _search_async  # pure async body of R05
# from my_package.chat_store import CHATS, load_chats_from_jsonl

configure_zeus_client()  # before other zeus_client imports in this module if any

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Option A — context manager
    async with ZeusClient():
        cfg = await load_config()
        # optional: await sync_chat_requests(cfg) when on_startup
        # load_chats_from_jsonl()
        yield
    # ZeusClient.__aexit__ closes HTTP

    # Option B — manual:
    # await init_http()
    # ...
    # yield
    # await close_http()

app = FastAPI(lifespan=lifespan)

class SearchBody(BaseModel):
    query: str
    chat_id: str | None = None

@app.post("/api/search")
async def api_search(body: SearchBody):
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(400, detail={"error": "empty query"})
    try:
        result = await _search_async(query, body.chat_id)
    except ValueError as e:
        raise HTTPException(400, detail={"error": str(e)}) from e
    except Exception as e:
        # map httpx.HTTPError → 502 with "network error: …" if you match Flask behavior
        raise HTTPException(502, detail={"error": f"network error: {e}"}) from e
    if result.get("error"):
        status = 502 if "network error" in result["error"] else 400
        raise HTTPException(status, detail=result)
    return result

@app.get("/api/tool-order")
async def api_tool_order():
    return build_tool_order(CHATS)
```

**Do not** call `run_coro` from FastAPI handlers — await `_search_async` directly.

**Reference**: `zeus_client.ZeusClient`, `init_http`, `close_http`; API shape from R09 / [API_CONTRACT.md](API_CONTRACT.md)

**Failures**: Blocking sync I/O on the event loop; double `init_http` without close; importing `zeus_client` before `configure_zeus_client()`

**Related**: R03, R04, R05, R09

---

## R03 — HTTP lifecycle

**When**: App process start and exit.

**Why**: Library HTTP client must be initialized once; cleanup on shutdown.

**Code** (Flask / TravelPlan):

```python
def startup() -> None:
    global _started
    if _started:
        return
    _ensure_loop()
    configure_zeus_client()
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)

    from zeus_client import init_http, load_config
    from travel_planner.chat_store import load_chats_from_jsonl

    run_coro(init_http())
    _sync_chat_requests_on_startup(run_coro(load_config()))  # R04
    load_chats_from_jsonl()
    _started = True

def shutdown() -> None:
    from zeus_client import close_http
    try:
        run_coro(close_http(), timeout=10)
    except Exception:
        pass

atexit.register(shutdown)
```

Call `startup()` from the app factory (`create_app()`).

**Preferred library API**:

```python
async with ZeusClient():
    ...
# or
await init_http()
# ...
await close_http()
```

**Reference**: `src/travel_planner/async_runner.py`, `src/travel_planner/app.py`

**Failures**:

| Symptom | Fix |
|---------|-----|
| `HTTP client not initialised` | Call `init_http()` / `ZeusClient` before agent APIs |
| Resource warnings on exit | Register shutdown / use lifespan |

**Related**: R02, R02b, R04

---

## R04 — Startup catalog sync

**When**: `chat_requests_sync.on_startup` is true (TravelPlan default).

**Code**:

```python
def _sync_chat_requests_on_startup(cfg: dict) -> None:
    sync_cfg = cfg.get("chat_requests_sync") or {}
    if not sync_cfg.get("on_startup"):
        return

    from zeus_client import logger, sync_chat_requests

    try:
        result = run_coro(sync_chat_requests(cfg))  # FastAPI: await sync_chat_requests(cfg)
    except Exception as e:
        logger.warning("startup chat_requests sync failed: %s", e)
        return

    if result.synced:
        logger.info("startup chat_requests sync: updated %d catalog(s)", len(result.synced))
    if result.skipped:
        logger.info("startup chat_requests sync: skipped %d unchanged catalog(s)", len(result.skipped))
    if result.errors:
        logger.warning("startup chat_requests sync: %d error(s): %s", len(result.errors), result.errors)
```

TravelPlan config:

```json
"chat_requests_sync": {
  "scopes": "from_contracts",
  "modes": ["travel_booking", "analytics"],
  "on_startup": true
}
```

**Reference**: `async_runner.py`; [CONFIG.md](CONFIG.md) §`chat_requests_sync`

**Failures**: Sync fails at boot → log warning, continue with on-disk/bundled catalogs (TravelPlan does not crash the app). Missing mode file → later `run_agent` error for that mode.

**Related**: R12, [CATALOGS_AND_CONTRACTS.md](CATALOGS_AND_CONTRACTS.md)

---

## R05 — Domain `run_agent` wrapper

**When**: Any search/chat turn.

**Why**: Centralize config resolution, domain prompt, mode/sample, structured output, and error mapping.

**Domain prompt** (travel — replace for other domains):

```python
TRAVEL_PROMPT_PREFIX = (
    "Find travel destinations that match these preferences. "
    "Use Zeus V2 search, find, or pipeline as needed to retrieve real destination data. "
    "Prefer results that include name, description, and image when available.\n\n"
    "User preferences:\n"
)
message = TRAVEL_PROMPT_PREFIX + query.strip()
```

**Core call** (from `search.py`, inside chat lock — see R08):

```python
from zeus_client import (
    load_config,
    logger,
    normalize_api_version,
    resolve_llm_provider_config,
    resolve_zeus_config,
    run_agent,
)

cfg = await load_config()
zcfg = resolve_zeus_config(cfg)
zeus_url = (zcfg.get("url") or "").rstrip("/")
if not zeus_url:
    raise ValueError("no Zeus URL configured (edit config.json)")

provider = resolve_llm_provider_config(cfg)
base_url = (provider.get("base_url") or "").rstrip("/")
api_key = provider.get("api_key") or ""
if not api_key:
    raise ValueError("llm_provider has no api_key set (edit config.json)")
model = (provider.get("models") or ["gpt-4o"])[0]

api_version = normalize_api_version(cfg.get("default_api_version", "v2"))
mode = cfg.get("default_mode", "travel_booking")
sample = cfg.get("default_sample", "travel-sample")
triple = cfg.get("samples", {}).get(sample, {})
bucket = triple.get("bucket", sample)
scope = triple.get("scope", "_default")
collection = triple.get("collection", "_default")

answer, trace, new_turns, session_meta, structured = await run_agent(
    zeus_url,
    zcfg,
    base_url,
    api_key,
    model,
    api_version,
    mode,
    bucket,
    scope,
    collection,
    message,
    prior_turns,
    optimized=True,
    provider_id=provider_id,
    conv_id=chat_id,
    zeus_session_id=prior_sid,
    zeus_round=prior_round,
    structured=True,
    output_schema=DEMO_OUTPUT_SCHEMA,  # R06
)
```

### `run_agent` signature (library)

```text
run_agent(
  zeus_url, zcfg, base_url, api_key, model, api_version, mode,
  bucket, scope, collection, user_msg, prior_turns,
  optimized=True, provider_id=None, conv_id=None,
  zeus_session_id="", zeus_round=0,
  hooks=None, structured=False, output_schema=None,
)
```

| `structured` | Return value |
|--------------|--------------|
| `False` (default) | `(answer, trace, turns, session_meta)` |
| `True` | `(answer, trace, turns, session_meta, StructuredAgentResponse)` |

`StructuredAgentResponse` fields used by TravelPlan: `zeus_data`, plus serialized via `dataclasses.asdict` for the API.

**Reference**: `src/travel_planner/search.py`, `zeus_client/agent/loop.py`

**Failures**:

| Error | Cause |
|-------|--------|
| `no Zeus URL configured` | Empty `zeus.url` and no `ZEUS_URL` |
| `llm_provider has no api_key` | Empty key in config |
| `no chat_request file for mode '…'` | Missing catalog for `default_mode` |
| Network errors | Zeus/LLM down → wrap as `network error: …` for HTTP 502 |

**Related**: R06, R07, R08, [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md)

---

## R06 — `output_schema` allowlist for UI cards

**When**: UI shows entity cards; you need filtered `structured.zeus_data` (not full docs).

**Precedence** (highest first):

1. `output_schema` argument to `run_agent`  
2. `guidance.injections.output_schema` in chat_request  
3. Live MINI-SCHEMA from the scope brief  

Reserved fields the client keeps: `id`, `doc_key`, `entity_type`.

**Code** (TravelPlan `output_schema.py`):

```python
_CARD_FIELDS = (
    "id", "name", "title", "destination", "destination_name",
    "description", "summary", "brief", "overview", "body", "snippet",
    "city", "location", "country", "state", "address", "directions",
    "type", "price", "price_range", "rate",
    "image", "image_url", "photo", "thumbnail", "picture", "img", "cover_image",
    "url", "website", "link",
)

DEMO_OUTPUT_SCHEMA: dict[str, list[str]] = {
    "Hotel": list(_CARD_FIELDS),
    "Destination": list(_CARD_FIELDS),
    "Airport": list(_CARD_FIELDS) + ["airportname", "faa", "icao"],
}
```

Pass into R05: `structured=True, output_schema=DEMO_OUTPUT_SCHEMA`.

**Reference**: `src/travel_planner/output_schema.py`, `.grok/guides/DEMO_OUTPUT_SCHEMA.md`, [templates/output_schema.py.stub](templates/output_schema.py.stub)

**Failures**: Empty cards (rows filtered away or wrong entity types); huge cards (schema too wide or omitted)

**Related**: R07, [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md)

---

## R07 — Result waterfall

**When**: Building `results[]` for the frontend after `run_agent`.

**Order** (TravelPlan `search.py`):

```python
from travel_planner.answer_parser import parse_markdown_answer, structured_answer_to_results
from travel_planner.results_parser import extract_destinations, zeus_data_to_results

# 1) Structured rows from client (preferred)
results = zeus_data_to_results(structured.zeus_data)

# 2) Parse tool-call traces if structured empty
if not results:
    results = extract_destinations(trace)

# 3) Markdown answer → structured_answer; optionally to cards
structured_answer = parse_markdown_answer(answer)
if not results and structured_answer:
    results = structured_answer_to_results(structured_answer)
```

### Card shape (`results_parser`)

Normalized cards include at least:

| Field | Source keys (first hit) |
|-------|-------------------------|
| `name` | name, destination, destination_name, then title/city/location |
| `description` | description, summary, brief, overview, body, snippet |
| `image` | image, image_url, photo, thumbnail, … |
| optional | location, address, city, state, country, price, url, area |

Also handles JSON blobs mistakenly placed in `description` (merge/promote fields).

`MAX_RESULTS = 20`.

**Reference**:

- `src/travel_planner/results_parser.py` — `zeus_data_to_results`, `extract_destinations`
- `src/travel_planner/answer_parser.py` — `parse_markdown_answer`, `structured_answer_to_results`
- `.grok/guides/MARKDOWN_ANSWER_PARSER.md`

**Failures**: Empty `results` but good `answer` → improve schema or markdown structure; raw JSON in card description → blob merge path / cleaner Zeus data

**Related**: R05, R06, [UI_CONTRACT.md](UI_CONTRACT.md)

---

## R08 — Multi-turn chat store + session IDs

**When**: Follow-up questions in one conversation.

**Why**: The library returns `session_meta` (`session_id`, `round`, …) and updated `turns`. The **app** owns persistence and must pass IDs back on the next turn.

**In-memory + JSONL** (TravelPlan):

```python
# chat_store.py
CHATS: dict[str, dict] = {}
CHAT_LOG_PATH = Path(os.environ.get("CHAT_LOG_PATH") or (PROJECT_ROOT / "data" / "chats.jsonl"))

async def chat_lock(chat_id: str) -> asyncio.Lock: ...
async def persist_chat(chat_id):  # upsert_chat event to JSONL
def load_chats_from_jsonl():      # replay on startup
```

**Per turn** (inside `async with` lock in `search.py`):

```python
chat_id = chat_id or ("travel_" + uuid.uuid4().hex[:12])

if chat_id not in CHATS:
    CHATS[chat_id] = {
        "title": query[:48],
        "created": time.time(),
        "turns": [],
        "traces": [],
    }
prior_turns = CHATS[chat_id]["turns"]
prior_sid = CHATS[chat_id].get("zeus_session_id", "") or ""
prior_round = int(CHATS[chat_id].get("zeus_round", 0) or 0)

# ... run_agent(..., prior_turns, zeus_session_id=prior_sid, zeus_round=prior_round)

CHATS[chat_id]["turns"] = new_turns
if session_meta.get("session_id"):
    CHATS[chat_id]["zeus_session_id"] = session_meta["session_id"]
    CHATS[chat_id]["zeus_round"] = session_meta.get("round") or prior_round
    CHATS[chat_id]["contract_status"] = session_meta.get("contract_status")

await persist_chat(chat_id)
```

Client must send `chat_id` from the previous response on follow-ups ([API_CONTRACT.md](API_CONTRACT.md)).

**Reference**: `src/travel_planner/chat_store.py`, `search.py`

**Failures**: New Zeus session every message (forgot to pass/store IDs); race on concurrent requests same `chat_id` (use per-chat lock); lost history after restart (call `load_chats_from_jsonl` on startup)

**Related**: R05, R03

---

## R09 — Minimal HTTP API (Flask)

**When**: Productized demo with TravelPlan-compatible routes.

**Code** (from `app.py`):

```python
from flask import Flask, jsonify, render_template, request
from zeus_client import build_tool_order

from travel_planner.async_runner import startup
from travel_planner.chat_store import CHATS
from travel_planner.search import run_search
from travel_planner.zeus_config import configure_zeus_client

def create_app() -> Flask:
    configure_zeus_client()
    startup()

    app = Flask(
        __name__,
        template_folder=str(PACKAGE_DIR / "templates"),
        static_folder=str(PACKAGE_DIR / "static"),
    )

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            tool_order=build_tool_order(CHATS),
            build_version=build_version,
        )

    @app.post("/api/search")
    def api_search():
        body = request.get_json(silent=True) or {}
        query = (body.get("query") or "").strip()
        if not query:
            return jsonify({"error": "empty query"}), 400

        result = run_search(query, body.get("chat_id"))
        if result.get("error"):
            status = 502 if "network error" in result["error"] else 400
            return jsonify(result), status
        return jsonify(result)

    @app.get("/api/tool-order")
    def api_tool_order():
        return jsonify(build_tool_order(CHATS))

    return app
```

### Success payload keys (TravelPlan)

`chat_id`, `query`, `answer`, `structured_answer`, `structured_response`, `results`, `trace`, `tool_order`, `target`, `api_version`, `mode`, `model`, `provider`, `zeus_connection`, `zeus_url`, `session_id`, `session_round`, `contract_status`

**Reference**: `src/travel_planner/app.py`, [templates/app.py.stub](templates/app.py.stub), [API_CONTRACT.md](API_CONTRACT.md)

**Failures**: Empty query 400; validation 400; network 502

**Related**: R02, R05, R10, R02b (FastAPI twin)

---

## R10 — Trace tool-order + vendored panel

**When**: Floating debug waterfall for demos.

**Default (v1)**: Vendor the built JS into package static assets.

```text
src/travel_planner/static/zeus_client_chat_trace.js
src/travel_planner/static/zeus_client_chat_trace.js.map
```

**Embed** (from `templates/index.html`):

```html
<script>
  window.ZeusTraceConfig = {
    toolOrder: {{ tool_order | tojson }},
    // optional: zeusApiUrl, auth, etc.
  };
</script>
<script src="/static/zeus_client_chat_trace.js" async></script>
```

**Tool order**:

- Server: `build_tool_order(CHATS)` on index render and in search response (`tool_order` key)
- Endpoint: `GET /api/tool-order` → JSON from same helper
- Client JS appends each search `trace` into the panel

**Optional CDN**: Not required. Only if operator provides a hosted bundle URL — still prefer vendored for offline demos. See [TRACE_PANEL.md](TRACE_PANEL.md).

**Reference**: `templates/index.html`, `static/zeus_client_chat_trace.js`, sibling repo `zeus_client_chat_trace` for rebuilds

**Failures**: 404 on JS path; empty panel (no `trace` in API response); wrong axes (stale tool_order)

**Related**: R09, [UI_CONTRACT.md](UI_CONTRACT.md)

---

## R11 — Docker monorepo client install

**When**: Containerized demo with sibling `zeus_client_python`.

**Dockerfile** (TravelPlan):

```dockerfile
FROM python:3.12-slim
WORKDIR /app

# Build context = monorepo parent (koten-ai/)
COPY demo_travel_sample/pyproject.toml demo_travel_sample/requirements.txt ./
COPY zeus_client_python /tmp/zeus_client_python
COPY demo_travel_sample/src ./src
COPY demo_travel_sample/data ./data
COPY demo_travel_sample/config.example.json .

RUN pip install --no-cache-dir /tmp/zeus_client_python \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps -e .

ENV PORT=5000
ENV ZEUS_CLIENT_CONFIG_DIR=/app
ENV ZEUS_CHAT_REQUESTS_DIR=/app/data/chat_requests

EXPOSE 5000
CMD ["python", "-m", "travel_planner"]
```

**Compose** essentials:

```yaml
services:
  travel-planner:
    build:
      context: ..
      dockerfile: demo_travel_sample/Dockerfile
    ports:
      - "5000:5000"
    environment:
      ZEUS_URL: "http://host.docker.internal:8080"
      ZEUS_CLIENT_CONFIG_DIR: "/app"
      ZEUS_CHAT_REQUESTS_DIR: "/app/data/chat_requests"
      CHAT_LOG_PATH: "/app/data/chats.jsonl"
    volumes:
      - ./config.json:/app/config.json
      - ./data:/app/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

**Reference**: `Dockerfile`, `docker-compose.yml`, [templates/Dockerfile.snippet](templates/Dockerfile.snippet)

**Failures**: Cannot reach Zeus (`localhost` inside container); missing sibling client COPY; secrets baked into image instead of volume mount

**Related**: [CONFIG.md](CONFIG.md) §Docker, [PREREQUISITES.md](PREREQUISITES.md)

---

## R12 — Config verification script

**When**: Preflight before demos or after catalog/contract changes.

**TravelPlan behavior** (`scripts/verify_config.py`):

1. `load_config` + `resolve_zeus_config`  
2. Print contract bindings for modes (`travel_booking`, `analytics`) on `travel-sample/_default`  
3. `init_http` → `sync_chat_requests(cfg, force=True)` (best-effort)  
4. For each mode: locate catalog via `chat_request_path`, compare stamped/computed hash to config, print tool names  

**Pattern for other demos**: Parameterize `MODES`, `BUCKET`, `SCOPE`; keep the hash comparison logic.

**Reference**: `scripts/verify_config.py`

**Failures**: Missing catalogs; hash mismatch (script prints the authoritative hash to paste into `scope_contracts`)

**Related**: R04, [CATALOGS_AND_CONTRACTS.md](CATALOGS_AND_CONTRACTS.md), [ACCEPTANCE.md](ACCEPTANCE.md)

---

## Cross-cutting flow (Flask TravelPlan)

```text
import travel_planner
  → configure_zeus_client()           # R01

create_app()
  → configure_zeus_client()           # R01
  → startup()                         # R02 loop + R03 init_http + R04 sync + load chats

POST /api/search                      # R09
  → run_search()                      # R02 run_coro
    → _search_async()                 # R05 + R08
      → run_agent(structured=True, output_schema=…)  # R05/R06
      → result waterfall              # R07
  → JSON + trace                      # R10 client panel
```

FastAPI replaces the left column with lifespan (R02b) and `await _search_async`.

---

## Related kit pages

| Page | Use |
|------|-----|
| [CONFIG.md](CONFIG.md) | Full config/env reference |
| [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md) | Non-travel knobs |
| [ANTI_EXAMPLES.md](ANTI_EXAMPLES.md) | What not to do |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Verification |
| [REFERENCE_TRAVELPLAN.md](REFERENCE_TRAVELPLAN.md) | File map |
