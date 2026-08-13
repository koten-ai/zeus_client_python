# Zeus Client V2 Documentation

Design documentation for **Version 2** of `kotenai-zeus-client`, rebuilt from first principles around first-class Zeus Engine Debug Tool integration.

| Document | Description |
| --- | --- |
| [DESIGN.md](./DESIGN.md) | Architecture: problem analysis, candidate comparison, selected journaled hexagonal runtime, lifecycles, tradeoffs |
| [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md) | Phased build plan (0–8), modules, APIs, tests, migration, risks |
| [SECURITY.md](./SECURITY.md) | Threat model, authz, secrets, redaction, replay, secure defaults |
| [BEST_PRACTICES.md](./BEST_PRACTICES.md) | Engineering standards: code, API, testing, CI/CD, observability |
| [MIGRATION.md](./MIGRATION.md) | V1→V2 map, compat shims, demo_yelp notes, cutover gate |

## Status

**Beta candidate on `feat/V2`** — dual-tree (`src/` = 0.3.1 `zeus_client`; `src_v2/zeus_client` → `zeus_client_v2` **2.0.0b1**). Claim level **candidate** per `sdk_bootstrap.pins.json`. Phase 8 hardening + compat + MIGRATION landed. **GA cutover train in progress** on `feat/ZCP-ga-cutover-2.0.0` — epic [ZCP-33](https://kotenai.atlassian.net/browse/ZCP-33); see [MIGRATION.md](./MIGRATION.md) §GA cutover train.

## Selected architecture (one paragraph)

V2 is a **journaled hexagonal runtime**: domain use-cases (agent, data verbs, typeahead, catalog) talk to ports; HTTP/LLM/Hub are adapters; every meaningful action appends an immutable **Execution Journal** event. Detective briefing, session-trace multi-hop posts, OTLP, and timeline views are **projectors** over that journal. Debug is structural, not a bolt-on `trace` dict.

## Reading order

1. DESIGN §1–4 (problem + selection)  
2. DESIGN §4.8 (debug architecture)  
3. IMPLEMENTATION_GUIDE phases 0–8  
4. SECURITY  
5. BEST_PRACTICES (use as PR review bar)
