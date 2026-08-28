# Zeus Client V2 Documentation

Design documentation for **Version 2** of `kotenai-zeus-client`, rebuilt from first principles around first-class Zeus Engine Debug Tool integration.

| Document | Description |
| --- | --- |
| [DESIGN.md](./DESIGN.md) | Architecture: problem analysis, candidate comparison, selected journaled hexagonal runtime, lifecycles, tradeoffs |
| [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md) | Phased build plan (0–8), modules, APIs, tests, migration, risks |
| [SECURITY.md](./SECURITY.md) | Threat model, authz, secrets, redaction, replay, secure defaults |
| [JAILBREAK_ATTEMPTS.md](./JAILBREAK_ATTEMPTS.md) | Red-team catalog: regex hits vs misses, Layer A dodge, retrieval injection (family SoT: [`JAILBREAK_ATTEMPTS_SECURITY.md`](https://github.com/koten-ai/zeus_client_design/blob/main/docs/JAILBREAK_ATTEMPTS_SECURITY.md)) |
| [BEST_PRACTICES.md](./BEST_PRACTICES.md) | Engineering standards: code, API, testing, CI/CD, observability |
| [MIGRATION.md](./MIGRATION.md) | V1→V2 map, compat shims, demo_yelp notes, cutover gate |
| [MULTI_AGENT.md](./MULTI_AGENT.md) | Pattern B jobs/units seam; claim `docs` not `demo` |
| [T9_TAG_MATRIX_HANDOFF.md](./T9_TAG_MATRIX_HANDOFF.md) | Human gate: tag `v2.0.0`, GH Release, design MATRIX, pins |

## Status

**GA cutover code on `main`** — package **2.0.0**, default `import zeus_client` → **ZeusRuntime** tree; temporary `zeus_client_v2` alias (deprecated). Claim level remains **`candidate`** per `sdk_bootstrap.pins.json` until human MATRIX. Epic [ZCP-33](https://kotenai.atlassian.net/browse/ZCP-33); remaining **T9** = [T9_TAG_MATRIX_HANDOFF.md](./T9_TAG_MATRIX_HANDOFF.md) ([ZCP-43](https://kotenai.atlassian.net/browse/ZCP-43)).

## Selected architecture (one paragraph)

V2 is a **journaled hexagonal runtime**: domain use-cases (agent, data verbs, typeahead, catalog) talk to ports; HTTP/LLM/Hub are adapters; every meaningful action appends an immutable **Execution Journal** event. Detective briefing, session-trace multi-hop posts, OTLP, and timeline views are **projectors** over that journal. Debug is structural, not a bolt-on `trace` dict.

## Reading order

1. DESIGN §1–4 (problem + selection)  
2. DESIGN §4.8 (debug architecture)  
3. IMPLEMENTATION_GUIDE phases 0–8  
4. SECURITY  
5. BEST_PRACTICES (use as PR review bar)
