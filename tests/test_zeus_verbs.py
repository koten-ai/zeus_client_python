"""Tests for zeus_client.zeus.verbs — direct V2 runners (no pipeline)."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from zeus_client.constants import V2_DOCS_VERB_ORDER
from zeus_client.zeus import verbs as v

ZEUS_URL = "http://zeus.test:8080"
BUCKET = "yelp-data"
SCOPE = "_default"
COLL = "_default"
HEADERS = {"X-Zeus-Session": "sid-test"}


@pytest.fixture(autouse=True)
def _respx(respx_mock):
    yield


def test_exposed_verbs_exclude_pipeline():
    assert "pipeline" not in v.EXPOSED_V2_VERBS
    assert "pipeline" not in v.EXPOSED_V2_VERB_SET
    for name in V2_DOCS_VERB_ORDER:
        if name == "pipeline":
            continue
        assert name in v.EXPOSED_V2_VERB_SET


def test_helpers_cover_exposed_except_typeahead_search_name():
    # run_search is typeahead in suggest; raw search is run_search_verb.
    assert set(v.RUN_VERB_HELPERS) == set(v.EXPOSED_V2_VERBS)
    assert "pipeline" not in v.RUN_VERB_HELPERS
    assert hasattr(v, "run_find")
    assert hasattr(v, "run_search_verb")
    assert not hasattr(v, "run_pipeline")


@pytest.mark.asyncio
async def test_run_verb_rejects_pipeline():
    r = await v.run_verb(
        "pipeline",
        {"steps": []},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
        zeus_headers=HEADERS,
    )
    assert not r.ok
    assert r.status == 0
    assert "pipeline is not exposed" in (r.error or "")


@pytest.mark.asyncio
async def test_run_verb_requires_auth():
    r = await v.run_verb(
        "find",
        {"entity_type": "Business"},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
    )
    assert not r.ok
    assert "zeus_headers" in (r.error or "")


@pytest.mark.asyncio
async def test_run_find_collection_path(http_client):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLL}/find"
    route = respx.post(url).mock(
        return_value=httpx.Response(
            200,
            json={"status": "ok", "items": [{"id": "n1"}]},
            headers={"X-Zeus-Req-Id": "req-find-1"},
        )
    )
    r = await v.run_find(
        {"entity_type": "Business", "where": {"name": "Pathmark"}, "limit": 5},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
        collection=COLL,
        zeus_headers=HEADERS,
    )
    assert r.ok
    assert r.verb == "find"
    assert r.req_id == "req-find-1"
    assert r.body["items"][0]["id"] == "n1"
    assert json.loads(route.calls.last.request.content)["where"]["name"] == "Pathmark"
    assert route.calls.last.request.headers["X-Zeus-Scope"] == f"{BUCKET}/{SCOPE}"
    assert route.calls.last.request.headers["X-Zeus-Mode"] == "analytics"


@pytest.mark.asyncio
async def test_run_get_and_search_verb(http_client):
    get_url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLL}/get"
    search_url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLL}/search"
    respx.post(get_url).mock(
        return_value=httpx.Response(200, json={"items": [{"id": "n1"}]})
    )
    respx.post(search_url).mock(
        return_value=httpx.Response(200, json={"result": {"src_keys": ["biz:1"]}})
    )

    g = await v.run_get(
        {"ids": ["n1"], "include": ["body"]},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
        zeus_headers=HEADERS,
    )
    assert g.ok and g.verb == "get"

    s = await v.run_search_verb(
        {"strategy": "fts", "query_text": "sushi", "limit": 3},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
        zeus_headers=HEADERS,
    )
    assert s.ok and s.verb == "search"
    assert s.body["result"]["src_keys"] == ["biz:1"]


@pytest.mark.asyncio
async def test_run_explain_bare_and_describe_scope(http_client):
    exp_url = f"{ZEUS_URL}/v2/explain"
    desc_url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/describe"
    respx.post(exp_url).mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.post(desc_url).mock(return_value=httpx.Response(200, json={"brief": "x"}))

    e = await v.run_explain(
        {"topic": "fts"},
        zeus_url=ZEUS_URL,
        zeus_headers=HEADERS,
    )
    assert e.ok and e.url.endswith("/v2/explain")

    d = await v.run_describe(
        {},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
        zeus_headers=HEADERS,
    )
    assert d.ok and d.url.endswith(f"/v2/{BUCKET}/{SCOPE}/describe")


@pytest.mark.asyncio
async def test_run_verb_http_error_status(http_client):
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLL}/project"
    respx.post(url).mock(return_value=httpx.Response(422, text="bad fields"))
    r = await v.run_project(
        {"ids": ["n1"], "fields": ["name"]},
        zeus_url=ZEUS_URL,
        bucket=BUCKET,
        scope=SCOPE,
        zeus_headers=HEADERS,
    )
    assert not r.ok
    assert r.status == 422
    assert "422" in (r.error or "")


@pytest.mark.asyncio
async def test_run_verb_from_config(http_client, monkeypatch):
    async def fake_auth(zeus_url, zcfg, bucket=None, scope=None, force=False):
        return {"X-Zeus-Session": "from-cfg"}, "ok"

    monkeypatch.setattr(v, "resolve_zeus_auth", fake_auth)
    url = f"{ZEUS_URL}/v2/{BUCKET}/{SCOPE}/{COLL}/find"
    respx.post(url).mock(return_value=httpx.Response(200, json={"items": []}))

    cfg = {
        "default_sample": "yelp",
        "samples": {
            "yelp": {"bucket": BUCKET, "scope": SCOPE, "collection": COLL},
        },
        "zeus": {"url": ZEUS_URL, "auth_mode": "basic", "username": "u", "password": "p"},
    }
    r = await v.run_verb_from_config(
        "find",
        {"entity_type": "Business", "limit": 1},
        cfg,
    )
    assert r.ok
    assert r.verb == "find"


def test_verb_result_to_dict():
    r = v.VerbResult(
        verb="find",
        status=200,
        text="{}",
        url="http://z/v2/b/s/c/find",
        body={},
    )
    d = r.to_dict()
    assert d["ok"] is True
    assert d["verb"] == "find"
