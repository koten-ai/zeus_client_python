"""Typeahead search unit/contract tests (ZCP-10)."""

from __future__ import annotations

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort
from zeus_client.application.typeahead import (
    SuggestHit,
    SuggestOptions,
    merge_hits,
    run_typeahead_search,
    src_keys_from_fts_payload,
)
from zeus_client.config.models import DataTarget, RuntimeConfig, ZeusEndpointConfig
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.runtime import ZeusRuntime


def test_merge_hits_dedupes_id_and_name_fts_first() -> None:
    a = SuggestHit(id="biz:1", name="Sushi Place", source="fts")
    b = SuggestHit(id="1", name="Other", source="find")  # same norm id
    c = SuggestHit(id="2", name="sushi place", source="find")  # same name
    d = SuggestHit(id="3", name="Ramen", source="find")
    out = merge_hits([a], [b, c, d], limit=10)
    assert [h.id for h in out] == ["biz:1", "3"]


def test_src_keys_from_fts_payload() -> None:
    keys = src_keys_from_fts_payload({"result": {"src_keys": ["biz:a", "biz:b", "biz:a"]}})
    assert keys == ["biz:a", "biz:b"]


@pytest.mark.asyncio
@respx.mock
async def test_typeahead_fts_default_not_hybrid() -> None:
    base = "http://zeus.test:8080"
    route = respx.post(f"{base}/v2/yelp-data/_default/_default/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "src_keys": ["biz:1"],
                    "items": [
                        {
                            "score": 1.5,
                            "node": {"doc_key": "biz:1", "name": "Sushi", "city": "SF"},
                        }
                    ],
                }
            },
            headers={"X-Zeus-Req-Id": "fts-1"},
        )
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=base, auth_mode="none"),
        secrets=EnvSecretStore(environ={}),
        journal=InMemoryJournal(),
        turn_id="t",
    )
    try:
        result = await run_typeahead_search(
            port,
            "sushi",
            target=DataTarget(),
            options=SuggestOptions(limit=5),
        )
    finally:
        await port.aclose()

    assert route.called
    body = route.calls.last.request.read()
    assert b'"strategy": "fts"' in body or b'"strategy":"fts"' in body
    assert b"hybrid" not in body
    assert result.fast_tier is True
    assert result.ai_process_result is False
    assert result.fts_req_id == "fts-1"
    assert result.count == 1
    assert result.hits[0].name == "Sushi"


@pytest.mark.asyncio
@respx.mock
async def test_rt_data_search() -> None:
    base = "http://zeus.test:8080"
    respx.post(url__startswith=f"{base}/v2/").mock(
        return_value=httpx.Response(
            200,
            json={"result": {"items": [{"node": {"id": "x", "name": "X"}}]}},
            headers={"X-Zeus-Req-Id": "s1"},
        )
    )
    cfg = RuntimeConfig(zeus=ZeusEndpointConfig(url=base, auth_mode="none"))
    port = HttpxZeusPort(endpoint=cfg.zeus, secrets=EnvSecretStore(environ={}), turn_id="t")
    async with ZeusRuntime(cfg, zeus=port) as rt:
        r = await rt.data.search("ab")
        assert r.fts_req_id == "s1"
        assert r.count >= 1


@pytest.mark.asyncio
async def test_short_query_skips_network() -> None:
    class Boom:
        async def call_verb(self, req):  # noqa: ANN001
            raise AssertionError("should not call zeus for short q")

    r = await run_typeahead_search(Boom(), "a", target=DataTarget())  # type: ignore[arg-type]
    assert r.count == 0
    assert r.source == "none"
