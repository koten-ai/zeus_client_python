"""Contract tests for /v2/agent_memory HTTP adapter (ZF-WISH-001)."""

from __future__ import annotations

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.agent_memory import HttpxAgentMemoryClient
from zeus_client.config.models import ZeusEndpointConfig
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.domain.journal.events import EVENT_ZEUS_HOP


@pytest.mark.asyncio
@respx.mock
async def test_status_recall_write_shapes_and_journal() -> None:
    base = "http://zeus.test:8080"
    respx.get(f"{base}/v2/agent_memory/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "enabled": True,
                "store": True,
                "embedder": True,
                "recall_mode": "cosine_scan",
                "feature": "semantic_agent_cache",
            },
            headers={"X-Zeus-Req-Id": "req-status"},
        )
    )
    respx.post(f"{base}/v2/agent_memory/recall").mock(
        return_value=httpx.Response(
            200,
            json={
                "blocks": [
                    {
                        "block_id": "amb_1",
                        "type": "profile",
                        "text": "prefers nonstop",
                        "summary": "short nonstop",
                        "score": 0.82,
                        "created_at": "2026-08-07T12:00:00Z",
                    }
                ],
                "embed_model": "lab",
                "mode": "cosine_scan",
                "latency_ms": 4,
            },
            headers={"X-Zeus-Req-Id": "req-recall"},
        )
    )
    respx.post(f"{base}/v2/agent_memory/blocks").mock(
        return_value=httpx.Response(
            201,
            json={
                "block_id": "amb_2",
                "type": "conversational",
                "embed_model": "lab",
                "ttl_seconds": 604800,
            },
            headers={"X-Zeus-Req-Id": "req-write"},
        )
    )
    journal = InMemoryJournal()
    port = HttpxAgentMemoryClient(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        journal=journal,
        turn_id="turn-1",
    )
    st = await port.status()
    assert st.enabled is True
    assert st.store is True
    assert await port.available() is True
    rec = await port.recall("cheap nonstop flights", top_k=5, types=["profile"])
    assert rec.ok is True
    assert rec.req_id == "req-recall"
    assert rec.blocks[0].summary == "short nonstop"
    assert "embedding" not in rec.blocks[0].to_mapping()
    wr = await port.write_block("User prefers nonstop flights under 6h", type="profile")
    assert wr.ok is True
    assert wr.block_id == "amb_2"
    hops = [e for e in journal.events() if e.type == EVENT_ZEUS_HOP]
    assert len(hops) == 3
    assert all("text" not in (e.data or {}) for e in hops)
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_status_404_unavailable() -> None:
    base = "http://zeus.test:8080"
    respx.get(f"{base}/v2/agent_memory/status").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    port = HttpxAgentMemoryClient(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    st = await port.status()
    assert st.enabled is False
    assert await port.available() is False
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_recall_timeout_is_result_not_raise() -> None:
    base = "http://zeus.test:8080"
    respx.post(f"{base}/v2/agent_memory/recall").mock(
        side_effect=httpx.TimeoutException("deadline")
    )
    port = HttpxAgentMemoryClient(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
    )
    rec = await port.recall("query that is long enough", timeout_ms=20)
    assert rec.ok is False
    assert rec.error == "timeout" or "deadline" in (rec.error or "")
    assert rec.skip_reason == "timeout"
    await port.aclose()
