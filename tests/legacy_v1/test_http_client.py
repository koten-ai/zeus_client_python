"""Shared httpx AsyncClient singleton."""
import httpx
import pytest

import zeus_client.http_client as hc


@pytest.mark.asyncio
async def test_init_client_and_close():
    hc._http = None
    await hc.init_http()
    c = hc.client()
    assert isinstance(c, httpx.AsyncClient)
    await hc.close_http()
    assert hc._http is None


@pytest.mark.asyncio
async def test_close_http_when_already_none():
    hc._http = None
    await hc.close_http()
    assert hc._http is None


@pytest.mark.asyncio
async def test_client_raises_before_init():
    hc._http = None
    with pytest.raises(RuntimeError, match="not initialised"):
        hc.client()