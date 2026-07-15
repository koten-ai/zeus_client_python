# Configuration

**Status**: Active (fleshed from TravelPlan + `kotenai-zeus-client`)  
**Related**: [templates/config.example.json](templates/config.example.json), recipe R01  
**Sources**: `config.example.json`, `src/travel_planner/zeus_config.py`, `zeus_client_python/src/config.py`, `zeus_client_python/src/constants.py`

---

## 1. Import-time environment rule

`zeus_client.constants` reads environment variables when the module is **first imported**. Paths that depend on those vars (`USER_CONFIG_DIR`, `CONFIG_PATH`, `user_chat_requests_dir()`, etc.) are fixed at that moment.

**Set env before any `import zeus_client`.**

TravelPlan does this in two places:

1. `travel_planner/__init__.py` calls `configure_zeus_client()` at package import  
2. `create_app()` / `startup()` call it again defensively  

```python
# src/travel_planner/zeus_config.py (pattern)
import os
from pathlib import Path

PROJECT_ROOT = Path(...)  # directory that contains config.json

def configure_zeus_client() -> None:
    os.environ.setdefault("ZEUS_CLIENT_CONFIG_DIR", str(PROJECT_ROOT))
    os.environ.setdefault(
        "ZEUS_CHAT_REQUESTS_DIR",
        str(PROJECT_ROOT / "data" / "chat_requests"),
    )
    os.environ.setdefault("CHAT_LOG_PATH", str(PROJECT_ROOT / "data" / "chats.jsonl"))
```

```python
# src/travel_planner/__init__.py
from travel_planner.zeus_config import configure_zeus_client

configure_zeus_client()  # before any zeus_client import from this package
```

Template: [templates/zeus_config.py](templates/zeus_config.py)

### Environment variables

| Variable | Read by | Purpose | TravelPlan default |
|----------|---------|---------|-------------------|
| `ZEUS_CLIENT_CONFIG_DIR` | `constants.user_config_dir()` | Directory containing `config.json` | project root |
| `ZEUS_CHAT_REQUESTS_DIR` | `constants.user_chat_requests_dir()` | Local stamped/synced catalogs | `data/chat_requests` |
| `CHAT_LOG_PATH` | app `chat_store` + library default | Multi-turn JSONL | `data/chats.jsonl` |
| `ZEUS_URL` | `resolve_zeus_config()` only | **Runtime** override of `zeus.url` (not written back to disk) | Compose sets `http://host.docker.internal:8080` |
| `PORT` | app `__main__` | HTTP listen port | `5000` |
| `ENVIRONMENT` | app | `dev` enables Flask debug | — |

### Path resolution (library)

| Path | Formula |
|------|---------|
| Config file | `$ZEUS_CLIENT_CONFIG_DIR/config.json` (else `~/.config/zeus_client/config.json`) |
| User catalogs | `$ZEUS_CHAT_REQUESTS_DIR` (else `$ZEUS_CLIENT_CONFIG_DIR/chat_requests`) |
| Bundled catalogs | Package data `zeus_client/data/chat_requests` (fallback when user dir missing a mode) |

`load_config()` auto-creates `config.json` from `config.example.json` in the config dir, or from the package-bundled example, if the file is missing.

---

## 2. Annotated `config.json` (TravelPlan)

Copy `config.example.json` → `config.json` (gitignored). Never commit secrets.

```json
{
  "build_version": "",
  "_comment": "Travel planner config. Copy to config.json and fill in your keys.",

  "zeus": {
    "url": "http://host.docker.internal:8080",
    "auth_mode": "basic",
    "username": "demo_1",
    "password": "",
    "bearer_token": "",
    "session_id": "",
    "scope_credentials": {
      "travel-sample/_default": { "username": "demo_1", "password": "" }
    },
    "scope_contracts": {
      "travel-sample/_default": {
        "travel_booking": {
          "contract_id": "travel_booking_v2",
          "contract_hash": ""
        },
        "analytics": {
          "contract_id": "analytics_v4",
          "contract_hash": "md5:a148645f9763b39ea4117c1b35f739db"
        }
      }
    },
    "enable_durable_sessions": true
  },

  "llm_provider": {
    "label": "xAI Grok",
    "base_url": "https://api.x.ai/v1",
    "api_key": "",
    "models": [
      "grok-4-1-fast-non-reasoning",
      "grok-4-1-fast-reasoning",
      "grok-4",
      "grok-3-mini"
    ]
  },

  "chat_requests_sync": {
    "scopes": "from_contracts",
    "modes": ["travel_booking", "analytics"],
    "on_startup": true
  },

  "default_api_version": "v2",
  "default_mode": "travel_booking",
  "default_sample": "travel-sample",
  "samples": {
    "travel-sample": {
      "bucket": "travel-sample",
      "scope": "_default",
      "collection": "_default"
    }
  }
}
```

Generic placeholder template (other domains): [templates/config.example.json](templates/config.example.json)

---

## 3. Field reference

### Top-level

| Key | Type | Purpose |
|-----|------|---------|
| `build_version` | string | Shown in UI footer (TravelPlan reads from `config.json`) |
| `_comment` | string | Documentation only; stripped if config is saved via library `save_config` |
| `zeus` | object | Zeus connection + contracts (preferred) |
| `llm_provider` | object | Single LLM provider (preferred) |
| `chat_requests_sync` | object | Startup catalog pull from Zeus |
| `default_api_version` | string | `"v1"` or `"v2"` (TravelPlan uses `"v2"`) |
| `default_mode` | string | Agent mode / catalog key (e.g. `travel_booking`) |
| `default_sample` | string | Key into `samples` |
| `samples` | object | Named bucket/scope/collection triples |

### `zeus`

| Key | Purpose |
|-----|---------|
| `url` | Zeus Engine base URL (not the client UI). Overridden by `ZEUS_URL` at resolve time. |
| `auth_mode` | `none`, `basic`, `bearer`, or `session` |
| `username` / `password` | Global basic auth |
| `bearer_token` | When `auth_mode` is `bearer` |
| `session_id` | Reuse existing Zeus session when `auth_mode` is `session` |
| `scope_credentials` | Per-scope basic auth, keyed by `bucket/scope` (e.g. `travel-sample/_default`) |
| `scope_contracts` | Per-scope contract bindings (see below) |
| `enable_durable_sessions` | Create/rehydrate `/v2/session` across agent turns |

### `scope_contracts` shapes

Two shapes appear in the wild. TravelPlan uses the **mode-nested** form:

```json
"scope_contracts": {
  "travel-sample/_default": {
    "travel_booking": {
      "contract_id": "travel_booking_v2",
      "contract_hash": ""
    },
    "analytics": {
      "contract_id": "analytics_v4",
      "contract_hash": "md5:…"
    }
  }
}
```

Library bundled example uses a **flat** form (single contract per scope):

```json
"scope_contracts": {
  "beer-sample/_default": {
    "contract_id": "",
    "contract_hash": ""
  }
}
```

`resolve_contract_for_scope(zcfg, bucket, scope, mode)` selects the binding for the active mode. Empty `contract_hash` is allowed for demos; stamped hashes from sync are preferred for drift checks (`scripts/verify_config.py`).

### `llm_provider`

| Key | Purpose |
|-----|---------|
| `label` | Display name; TravelPlan derives `provider_id` from first word (e.g. `"xAI Grok"` → `"xai"`) |
| `base_url` | OpenAI-compatible API root (e.g. `https://api.x.ai/v1`) |
| `api_key` | **Required** for search; empty → `ValueError` in `run_search` |
| `models` | List; **first entry** is the default model |

### `chat_requests_sync`

| Key | TravelPlan | Purpose |
|-----|------------|---------|
| `scopes` | `"from_contracts"` | Which scopes to sync (`from_contracts` uses keys in `scope_contracts`) |
| `modes` | `["travel_booking", "analytics"]` | Modes to pull |
| `on_startup` | `true` | App calls `sync_chat_requests(cfg)` during `startup()` (R04) |

Library default example uses `"scopes": "from_samples"`, `"modes": "auto"`, `"on_startup": false`. Demos that ship local catalogs can leave `on_startup` false if files already exist under `data/chat_requests/`.

### `samples` triple

```json
"samples": {
  "travel-sample": {
    "bucket": "travel-sample",
    "scope": "_default",
    "collection": "_default"
  }
}
```

`search.py` resolves:

```python
sample = cfg.get("default_sample", "travel-sample")
triple = cfg.get("samples", {}).get(sample, {})
bucket = triple.get("bucket", sample)
scope = triple.get("scope", "_default")
collection = triple.get("collection", "_default")
```

These three strings are passed positionally into `run_agent(...)`.

---

## 4. Resolvers (always use these)

```python
from zeus_client import load_config, resolve_zeus_config, resolve_llm_provider_config

cfg = await load_config()
zcfg = resolve_zeus_config(cfg)       # applies ZEUS_URL override
provider = resolve_llm_provider_config(cfg)
zeus_url = (zcfg.get("url") or "").rstrip("/")
```

| Function | Behavior |
|----------|----------|
| `load_config()` | Async; reads `$ZEUS_CLIENT_CONFIG_DIR/config.json`; normalizes legacy shapes in memory |
| `resolve_zeus_config(cfg)` | Returns `cfg["zeus"]` copy with optional `ZEUS_URL` override |
| `resolve_llm_provider_config(cfg)` | Returns `cfg["llm_provider"]` copy |
| `normalize_api_version(...)` | Normalize v1/v2 strings before `run_agent` |

Do **not** read only `zeus_connections[0]` or `providers[…]` in app code — normalization already collapses those into `zeus` / `llm_provider`.

---

## 5. Legacy config shapes

Still accepted by `normalize_config()` (in memory only):

| Legacy | Normalized to |
|--------|----------------|
| `zeus_connections: [ { name, url, ... } ]` + optional `default_zeus_connection` | `zeus` (first or named entry; strips `id`/`name`/`workbench_url`) |
| `providers: { id: { label, base_url, api_key, models } }` + optional `default_provider` | `llm_provider` (chosen entry; only those four fields kept) |

TravelPlan **ships modern keys** in `config.example.json`. Prefer modern for new demos.

JSON **does not allow `//` comments**. Use `"_comment": "..."` string keys. Invalid comments produce a clear `RuntimeError` from `load_config`.

---

## 6. Docker / Compose env (TravelPlan)

From `docker-compose.yml`:

```yaml
environment:
  ZEUS_URL: "http://host.docker.internal:8080"
  CHAT_LOG_PATH: "/app/data/chats.jsonl"
  ZEUS_CLIENT_CONFIG_DIR: "/app"
  ZEUS_CHAT_REQUESTS_DIR: "/app/data/chat_requests"
  PORT: "5000"
volumes:
  - ./config.json:/app/config.json
```

From `Dockerfile`:

```dockerfile
ENV ZEUS_CLIENT_CONFIG_DIR=/app
ENV ZEUS_CHAT_REQUESTS_DIR=/app/data/chat_requests
```

**Rule**: `config.json` `zeus.url` and/or `ZEUS_URL` must be host-reachable from the container. Do not use host `localhost` for Zeus when the app runs in Docker.

---

## 7. Catalogs on disk

TravelPlan keeps snapshots under:

```text
data/chat_requests/
├── by_use_case/
│   ├── chat_request_travel_booking_v2.json
│   └── chat_request_analytics_v2.json
└── travel-sample__default/
    ├── chat_request_travel_booking_v2.json
    ├── chat_request_analytics_v2.json
    └── chat_request_auto_v2.json
```

Scope-specific dirs use `bucket__scope` with leading `_` stripped from scope (`travel-sample/_default` → `travel-sample__default`). See `zeus_client.constants.scope_chat_requests_subdir`.

Catalog resolution order (library): scope-specific user dir → general user dir → package bundled data.

---

## 8. Application code that consumes config

| Step | Code (TravelPlan) |
|------|-------------------|
| Load | `cfg = await load_config()` |
| Zeus | `zcfg = resolve_zeus_config(cfg)` → `zcfg["url"]`, auth fields, contracts |
| LLM | `provider = resolve_llm_provider_config(cfg)` → `base_url`, `api_key`, `models[0]` |
| Mode | `cfg.get("default_mode", "travel_booking")` |
| Sample | `cfg["samples"][cfg["default_sample"]]` → bucket/scope/collection |
| API version | `normalize_api_version(cfg.get("default_api_version", "v2"))` |

Validation errors raised as `ValueError` (surfaced as HTTP 400):

- `no Zeus URL configured (edit config.json)`
- `llm_provider has no api_key set (edit config.json)`

---

## 9. Preflight verification

TravelPlan `scripts/verify_config.py`:

1. Prints `resolve_contract_for_scope` for `travel_booking` and `analytics`  
2. Optionally `sync_chat_requests(cfg, force=True)`  
3. Compares config hashes to stamped/computed catalog hashes  

Run from the demo repo after installing the client (or with `zeus_client_python/src` on `PYTHONPATH`).

See [CATALOGS_AND_CONTRACTS.md](CATALOGS_AND_CONTRACTS.md) and recipe **R12**.

---

## 10. Security checklist

- [ ] `config.json` is gitignored  
- [ ] No real `api_key` / passwords in `config.example.json`  
- [ ] Compose mounts secrets via volume, not `COPY` into the image  
- [ ] Prefer env override for URL in shared environments (`ZEUS_URL`)  

---

## 11. Related recipes

| Topic | Recipe |
|-------|--------|
| Env before import | R01 |
| Startup sync | R04 |
| `run_agent` wiring | R05 |
| Docker monorepo | R11 |
| Verify script | R12 |
