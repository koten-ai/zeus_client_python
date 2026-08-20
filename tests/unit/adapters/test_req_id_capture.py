"""req_id capture on success and error (CORRELATION_IDS §4)."""

from __future__ import annotations

import httpx
import pytest
import respx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http.catalog_remote import HttpxCatalogRemote
from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.errors import CatalogError
from zeus_client.domain.ids import new_zeus_req_id
from zeus_client.ports import VerbRequest

ZEUS = "http://zeus.test:8080"
RID = "16bd540b-5e26-4b2a-87ba-4727af320127"


@pytest.mark.asyncio
@respx.mock
async def test_verb_captures_req_id_on_200() -> None:
    respx.post(f"{ZEUS}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"X-Zeus-Req-Id": RID})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=ZEUS, auth_mode="none"),
        secrets=EnvSecretStore({}),
    )
    hop = await port.call_verb(
        VerbRequest(verb="find", body={}, target=DataTarget(), mode_header="analytics")
    )
    assert hop.req_id == RID
    sent = respx.calls.last.request
    assert "X-Zeus-Req-Id" not in sent.headers
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_verb_captures_req_id_on_409() -> None:
    respx.post(f"{ZEUS}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(409, json={"error": "contract"}, headers={"X-Zeus-Req-Id": RID})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=ZEUS, auth_mode="none"),
        secrets=EnvSecretStore({}),
    )
    hop = await port.call_verb(VerbRequest(verb="find", body={}, target=DataTarget()))
    assert hop.req_id == RID
    assert hop.ok is False
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_verb_pre_mint_sends_v4() -> None:
    minted = new_zeus_req_id()
    respx.post(f"{ZEUS}/v2/yelp-data/_default/_default/find").mock(
        return_value=httpx.Response(200, json={}, headers={"X-Zeus-Req-Id": minted})
    )
    port = HttpxZeusPort(
        endpoint=ZeusEndpointConfig(url=ZEUS, auth_mode="none"),
        secrets=EnvSecretStore({}),
    )
    hop = await port.call_verb(
        VerbRequest(verb="find", body={}, target=DataTarget(), pre_mint_req_id=True)
    )
    sent = respx.calls.last.request
    assert sent.headers.get("X-Zeus-Req-Id")
    assert hop.req_id == minted
    await port.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_catalog_remote_error_includes_req_id() -> None:
    respx.get(f"{ZEUS}/v1/ai/chat_request.json").mock(
        return_value=httpx.Response(404, text="missing", headers={"X-Zeus-Req-Id": RID})
    )
    remote = HttpxCatalogRemote(ZeusEndpointConfig(url=ZEUS, auth_mode="none"))
    with pytest.raises(CatalogError) as ei:
        await remote.fetch_chat_request("yelp-data", "_default", "analytics")
    assert ei.value.details.get("req_id") == RID
    assert remote.last_req_id == RID
    await remote.aclose()
