# Anti-examples

**Status**: Draft  
**Related**: [ACCEPTANCE.md](ACCEPTANCE.md), [RECIPES.md](RECIPES.md)

Patterns that **look** reasonable but break demos. Do not ship these.

---

## 1. Import `zeus_client` before setting env

```python
# BAD
from zeus_client import run_agent
os.environ["ZEUS_CLIENT_CONFIG_DIR"] = "..."
```

```python
# GOOD
configure_zeus_client()  # sets env first
from zeus_client import run_agent
```

---

## 2. Call async client from Flask without a loop

```python
# BAD
asyncio.run(run_agent(...))  # per request, breaks long-lived httpx / nested loops
```

Use **R02** background loop or switch to FastAPI (**R02b**).

---

## 3. Forget `init_http` / `ZeusClient`

Symptom: `HTTP client not initialised`.

---

## 4. Dump full Zeus documents into the UI

Skip `output_schema` / allowlist → huge cards, internal fields, PII risk.

Use **R06**.

---

## 5. Assume library owns multi-turn chat UI state

Library returns `session_meta`; **app** must persist `zeus_session_id` / `zeus_round` and `prior_turns`.

---

## 6. Point Docker app at `localhost:8080` for host Zeus

Use `host.docker.internal` (or compose DNS). See [PREREQUISITES.md](PREREQUISITES.md).

---

## 7. Invent alternate agent frameworks

Do not replace `run_agent` with ad-hoc LangChain/custom loops for this kit’s demos.

---

## 8. Commit secrets

Never commit real `api_key` / passwords in `config.json`.

---

## 9. Hard-code only travel field names for a non-travel domain

Use [DOMAIN_CUSTOMIZATION.md](DOMAIN_CUSTOMIZATION.md).

---

## 10. Depend on CDN for trace JS without offline fallback

v1 default is **vendored** JS. CDN is optional only.
