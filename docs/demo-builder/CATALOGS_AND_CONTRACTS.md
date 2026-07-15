# Catalogs and contracts (demo checklist)

**Status**: Draft  
**Related**: [CONFIG.md](CONFIG.md), recipes R04 / R12, SDK “Contracts & catalog”

---

## 1. What demos need

| Artifact | Purpose |
|----------|---------|
| Stamped or bundled `chat_request` for mode | Tools + prompts for `run_agent` |
| `scope_contracts` entry | contract_id / hash binding (recommended) |
| Local dir `ZEUS_CHAT_REQUESTS_DIR` | Offline/demo snapshots |

---

## 2. Local layout

```text
data/chat_requests/
├── by_use_case/
│   └── chat_request_<mode>_v2.json
└── <bucket>__<scope>/          # optional scope-specific
    └── ...
```

<!-- TODO: Match TravelPlan data/chat_requests layout -->

---

## 3. Sync on startup

Config:

```json
"chat_requests_sync": {
  "scopes": "from_contracts",
  "modes": ["travel_booking"],
  "on_startup": true
}
```

App: call `sync_chat_requests(cfg)` during startup (R04).

---

## 4. Green-before-first-search checklist

- [ ] Zeus reachable  
- [ ] Mode’s chat_request file present after sync or ship  
- [ ] `default_mode` matches a catalog  
- [ ] `default_sample` triple matches loaded data  
- [ ] `scope_contracts` keys use `bucket/scope` form  
- [ ] LLM api_key set  

Optional: [templates](templates/) + recipe R12 verify script.

---

## 5. Offline vs stamped

| Mode | When |
|------|------|
| Bundled / shipped catalogs | Offline demos, air-gapped |
| Synced stamped catalogs | Preferred for contract-aligned demos |

<!-- TODO: Expand from SDK contracts-and-catalog + FAQ -->

---

## 6. Common failures

| Symptom | Fix |
|---------|-----|
| `no chat_request file for mode '…'` | Sync or copy catalog; check `ZEUS_CHAT_REQUESTS_DIR` |
| Contract drift | Re-sync; update hash in config |
| Wrong scope key | Use `bucket/scope` consistently |
