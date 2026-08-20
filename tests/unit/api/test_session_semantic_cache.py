"""SessionAPI semantic_cache — flag off means zero HTTP."""

from __future__ import annotations

import httpx
import pytest
import respx

from zeus_client.config.models import RuntimeConfig, SemanticCacheConfig, ZeusEndpointConfig
from zeus_client.runtime import ZeusRuntime


@pytest.mark.asyncio
@respx.mock
async def test_flag_off_status_write_recall_zero_http() -> None:
    base = "http://zeus.test:8080"
    status_r = respx.get(f"{base}/v2/agent_memory/status").mock(
        return_value=httpx.Response(200, json={"enabled": True})
    )
    recall_r = respx.post(f"{base}/v2/agent_memory/recall").mock(
        return_value=httpx.Response(200, json={"blocks": []})
    )
    write_r = respx.post(f"{base}/v2/agent_memory/blocks").mock(
        return_value=httpx.Response(201, json={"block_id": "x"})
    )
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url=base, auth_mode="none"),
        semantic_cache=SemanticCacheConfig(enabled=False),
    )
    async with ZeusRuntime(cfg) as rt:
        st = await rt.session.semantic_cache.status()
        assert st.enabled is False
        rec = await rt.session.semantic_cache.recall("cheap nonstop flights")
        assert rec.skipped is True
        wr = await rt.session.semantic_cache.write("User prefers nonstop flights under 6h")
        assert wr.skipped is True
    assert status_r.call_count == 0
    assert recall_r.call_count == 0
    assert write_r.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_explicit_write_when_enabled() -> None:
    base = "http://zeus.test:8080"
    write_r = respx.post(f"{base}/v2/agent_memory/blocks").mock(
        return_value=httpx.Response(
            201,
            json={"block_id": "amb_9", "type": "profile", "ttl_seconds": 604800},
            headers={"X-Zeus-Req-Id": "req-w"},
        )
    )
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url=base, auth_mode="none"),
        semantic_cache=SemanticCacheConfig(enabled=True, dev_user_id="lab_user"),
    )
    async with ZeusRuntime(cfg) as rt:
        wr = await rt.session.semantic_cache.write(
            "User prefers nonstop flights under 6h", type="profile"
        )
        assert wr.ok is True
        assert wr.block_id == "amb_9"
    assert write_r.call_count == 1
    posted = write_r.calls[0].request
    import json

    body = json.loads(posted.content.decode("utf-8"))
    assert body["text"].startswith("User prefers")
    assert body["type"] == "profile"
    assert body["user_id"] == "lab_user"
    assert "embedding" not in body


@pytest.mark.asyncio
@respx.mock
async def test_write_denies_secrets() -> None:
    base = "http://zeus.test:8080"
    write_r = respx.post(f"{base}/v2/agent_memory/blocks").mock(
        return_value=httpx.Response(201, json={"block_id": "nope"})
    )
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url=base, auth_mode="none"),
        semantic_cache=SemanticCacheConfig(enabled=True, dev_user_id="u"),
    )
    async with ZeusRuntime(cfg) as rt:
        wr = await rt.session.semantic_cache.write(
            "Authorization: Bearer super-secret-token-value-here"
        )
        assert wr.skipped is True
        assert wr.skip_reason == "secrets"
    assert write_r.call_count == 0
