# Trace panel

**Status**: Draft  
**Related**: recipe R10, [UI_CONTRACT.md](UI_CONTRACT.md)

---

## 1. Default: vendored JS

Ship a built copy of the chat-trace bundle inside the demo:

```text
src/<package>/static/zeus_client_chat_trace.js
src/<package>/static/zeus_client_chat_trace.js.map   # optional
```

Reference: TravelPlan `src/travel_planner/static/zeus_client_chat_trace.js`  
Upstream package: sibling `zeus_client_chat_trace` (build → copy into static).

**v1 rule**: Prefer vendored assets so demos work offline and without CDN dependency.

---

## 2. Embed sketch

```html
<!-- TODO: exact data attributes / ZeusTraceConfig from TravelPlan index.html -->
<script src="/static/zeus_client_chat_trace.js" async></script>
```

App must expose:

- Trace payload from search response (`trace`)
- Tool order from `GET /api/tool-order` or inline `tool_order`

---

## 3. Tool-order endpoint

```http
GET /api/tool-order
```

Uses library `build_tool_order(chats)` (or equivalent). See [API_CONTRACT.md](API_CONTRACT.md).

---

## 4. Optional: CDN or sibling path

Not required for v1 demos. Document for operators who prefer it:

| Option | When | Notes |
|--------|------|--------|
| **Vendored** (default) | Always | Copy built JS into `static/` |
| Sibling build | Active development of trace UI | Build `zeus_client_chat_trace`, copy artifact |
| CDN | Shared hosted asset | Pin version; requires network; **optional** |

<!-- TODO: Add concrete CDN URL only if product publishes one -->

---

## 5. Config hooks

<!-- TODO: window.ZeusTraceConfig, data-zeus-api-url, auth token if any -->

---

## 6. Failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Panel blank | JS 404 | Vendor path / static route |
| Empty waterfall | Missing `trace` in API response | Check search wrapper |
| Wrong tool axis order | Stale tool-order | Refresh `/api/tool-order` |
