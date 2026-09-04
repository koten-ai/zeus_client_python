"""Phase 8 hardening: metrics, rate limit, compat, public surface (ZCP-22)."""

from __future__ import annotations

import warnings

import httpx
import pytest
import respx

from zeus_client import ZeusRuntime, __version__
from zeus_client.adapters.otlp import try_build_otlp_exporter
from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort
from zeus_client.compat.v1 import run_agent, run_search, run_verb, turn_result_as_v1_tuple
from zeus_client.config.models import (
    RateLimitPolicy,
    RuntimeConfig,
    ZeusEndpointConfig,
)
from zeus_client.domain.errors import ErrorCode, ZeusClientError
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.domain.messages import DebugBundle, TurnResult, TurnStatus
from zeus_client.observability.metrics import InMemoryMetrics
from zeus_client.observability.rate_limit import TokenBucket


def test_package_version_is_2_0_0() -> None:
    assert __version__ == "2.4.0"


def test_public_exports() -> None:
    import zeus_client as z

    for name in (
        "ZeusRuntime",
        "TurnResult",
        "VerbResult",
        "SuggestResult",
        "ClientSettings",
        "RateLimitPolicy",
        "ErrorCode",
        "compute_contract_hash",
        "peel_layer_a_summary",
    ):
        assert hasattr(z, name), name


def test_token_bucket_allows_burst_then_limits() -> None:
    b = TokenBucket(rate=1000.0, burst=3.0)
    assert b.allow()
    assert b.allow()
    assert b.allow()
    assert b.allow() is False


def test_metrics_incr_and_snapshot() -> None:
    m = InMemoryMetrics()
    m.incr("zeus_client_turns_total", labels={"status": "ok", "mode": "analytics"})
    m.incr("zeus_client_turns_total", labels={"status": "ok", "mode": "analytics"})
    m.observe("zeus_client_zeus_hop_latency_ms", 12.5, labels={"verb": "find"})
    snap = m.snapshot()
    assert snap["counters"]["zeus_client_turns_total"][0]["value"] == 2.0
    assert snap["histograms"]["zeus_client_zeus_hop_latency_ms"][0]["count"] == 1


def test_otlp_factory_default_null() -> None:
    exp = try_build_otlp_exporter(enabled=False)
    assert exp.enabled is False
    assert exp.export_events([{"type": "x"}]) == 0
    on = try_build_otlp_exporter(endpoint="http://127.0.0.1:4318", enabled=True)
    assert on.enabled is True
    assert on.export_events([{"type": "a"}, {"type": "b"}]) == 2
    on.shutdown()


def test_turn_result_as_v1_tuple() -> None:
    tr = TurnResult(
        answer="hi",
        status=TurnStatus.OK,
        structured=None,
        session=None,
        debug=DebugBundle(rounds=2, public_trace={"steps": []}, detective={"version": 1}),
        error=None,
        messages=(),
    )
    answer, trace, rounds, meta = turn_result_as_v1_tuple(tr)
    assert answer == "hi"
    assert rounds == 2
    assert trace["detective"]["version"] == 1
    assert meta == {}


@pytest.mark.asyncio
@respx.mock
async def test_typeahead_rate_limit_raises() -> None:
    base = "http://zeus.test:8080"
    respx.post(f"{base}/v2/yelp-data/_default/_default/search").mock(
        return_value=httpx.Response(
            200,
            json={"result": {"src_keys": [], "items": []}},
            headers={"X-Zeus-Req-Id": "r1"},
        )
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        journal=InMemoryJournal(),
        turn_id="t",
    )
    metrics = InMemoryMetrics()
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url=base, auth_mode="none"),
        rate_limit=RateLimitPolicy(
            typeahead_enabled=True,
            typeahead_rps=1.0,
            typeahead_burst=1.0,
        ),
    )
    try:
        async with ZeusRuntime(cfg, zeus=port, metrics=metrics) as rt:
            await rt.data.search("sushi")
            with pytest.raises(ZeusClientError) as ei:
                await rt.data.search("ramen")
            assert ei.value.code is ErrorCode.CLIENT_RATE_LIMITED
            snap = metrics.snapshot()
            assert "zeus_client_rate_limited_total" in snap["counters"]
    finally:
        await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_compat_run_search_and_verb_warn() -> None:
    base = "http://zeus.test:8080"
    respx.post(url__regex=r".*/search$").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "src_keys": ["biz:1"],
                    "items": [{"node": {"doc_key": "biz:1", "name": "Sushi"}}],
                }
            },
            headers={"X-Zeus-Req-Id": "s1"},
        )
    )
    respx.post(url__regex=r".*/find$").mock(
        return_value=httpx.Response(
            200,
            json={"result": {"items": []}},
            headers={"X-Zeus-Req-Id": "f1"},
        )
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        journal=InMemoryJournal(),
        turn_id="t",
    )
    cfg = RuntimeConfig(
        zeus=ZeusEndpointConfig(url=base, auth_mode="none"),
        rate_limit=RateLimitPolicy(typeahead_enabled=False),
    )
    try:
        async with ZeusRuntime(cfg, zeus=port) as rt:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                sug = await run_search("sushi", runtime=rt)
                vr = await run_verb(
                    "find",
                    {"entity_type": "Business", "limit": 1},
                    runtime=rt,
                )
            assert sug.count >= 1
            assert vr.ok is True
            assert any(issubclass(x.category, DeprecationWarning) for x in w)
    finally:
        await port.aclose()


@pytest.mark.asyncio
async def test_compat_run_agent_requires_message_and_warns() -> None:
    class _FakeAgent:
        async def run_turn(self, message: str, **kwargs):  # type: ignore[no-untyped-def]
            return TurnResult(
                answer=f"echo:{message}",
                status=TurnStatus.OK,
                structured=None,
                session=None,
                debug=DebugBundle(rounds=1),
                error=None,
                messages=(),
            )

    class _RT:
        def __init__(self) -> None:
            self.agent = _FakeAgent()
            self.config = RuntimeConfig()

    rt = _RT()  # type: ignore[assignment]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = await run_agent("ping", runtime=rt)  # type: ignore[arg-type]
        tup = await run_agent("ping", runtime=rt, legacy_tuple=True)  # type: ignore[arg-type]
    assert out.answer == "echo:ping"  # type: ignore[union-attr]
    assert tup[0] == "echo:ping"
    assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_rate_limit_policy_in_public_dict() -> None:
    pub = RuntimeConfig().to_public_dict()
    assert pub["rate_limit"]["typeahead_rps"] == 10.0
    assert pub["rate_limit"]["typeahead_burst"] == 20.0
