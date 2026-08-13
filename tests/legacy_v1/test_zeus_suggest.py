"""Unit tests for zeus_client.zeus.suggest (no live Zeus/CB)."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from zeus_client.zeus import suggest as sug


@pytest.fixture(autouse=True)
def _respx(respx_mock):
    yield


def test_src_keys_from_fts_payload_prefers_src_keys():
    payload = {
        "result": {
            "src_keys": ["biz:a", "biz:b", "biz:a"],
            "items": [{"node": {"doc_key": "biz:z"}, "score": 1.0}],
        }
    }
    assert sug.src_keys_from_fts_payload(payload) == ["biz:a", "biz:b"]


def test_src_keys_fallback_from_items():
    payload = {
        "result": {
            "items": [
                {"node": {"doc_key": "biz:1"}, "score": 2.0},
                {"node": {"id": "biz:2"}, "score": 1.5},
            ]
        }
    }
    assert sug.src_keys_from_fts_payload(payload) == ["biz:1", "biz:2"]
    scores = sug.scores_by_src_key(payload)
    assert scores["biz:1"] == 2.0
    assert scores["biz:2"] == 1.5


def test_rows_from_project_or_pipeline_shapes():
    assert sug.rows_from_project_or_pipeline(
        {"rows": {"rows": [{"name": "A"}, {"missing": True}]}}
    ) == [{"name": "A"}, {"missing": True}]
    assert sug.rows_from_project_or_pipeline({"result": {"rows": [{"name": "B"}]}}) == [
        {"name": "B"}
    ]
    assert sug.rows_from_project_or_pipeline(
        {"data": {"rows": {"rows": [{"name": "C"}]}}}
    ) == [{"name": "C"}]


def test_guess_city():
    assert sug.guess_city("sushi in Philadelphia") == "Philadelphia"
    assert sug.guess_city("Philadelphia") == "Philadelphia"
    assert sug.guess_city("sushi") is None


def test_row_to_hit_and_merge():
    a = sug.row_to_hit(
        {
            "doc_key": "biz:1",
            "name": "Sushi Place",
            "city": "Philly",
            "state": "PA",
            "stars": 4.5,
            "categories": ["Sushi", "Japanese"],
        },
        score=3.0,
        source="fts",
    )
    assert a is not None
    assert a.id == "biz:1"
    assert a.name == "Sushi Place"
    assert "★4.5" in a.subtitle
    assert "Philly" in a.subtitle
    b = sug.row_to_hit({"business_id": "biz:1", "name": "Sushi Place Dup"})
    c = sug.row_to_hit({"doc_key": "biz:2", "name": "Other"})
    merged = sug.merge_hits([a], [b, c], limit=8)
    assert [h.id for h in merged] == ["biz:1", "biz:2"]


def test_row_to_hit_skips_missing():
    assert sug.row_to_hit({"missing": True, "name": "X"}) is None


def test_couchbase_from_mapping_host_default():
    cb = sug.CouchbaseQueryConfig.from_mapping({}, zeus_url="http://127.0.0.1:8080")
    assert cb is not None
    assert cb.query_url == "http://127.0.0.1:8093"


def test_suggest_result_to_dict():
    hit = sug.SuggestHit(id="biz:1", name="N", stars=4.0)
    r = sug.SuggestResult(
        query="su",
        hits=(hit,),
        count=1,
        source="zeus_fts",
        sources=("zeus_fts",),
        target="yelp-data/_default/_default",
    )
    d = r.to_dict()
    assert d["count"] == 1
    assert d["results"][0]["name"] == "N"
    assert d["fast_tier"] is True
    assert d["ai_process_result"] is False


@pytest.mark.asyncio
async def test_run_search_short_query():
    r = await sug.run_search(
        "a",
        zeus_url="http://zeus.test:8080",
        bucket="yelp-data",
        scope="_default",
        zeus_headers={"X-Zeus-Session": "s"},
    )
    assert r.source == "none"
    assert r.hits == ()


@pytest.mark.asyncio
async def test_run_search_requires_auth():
    r = await sug.run_search(
        "sushi",
        zeus_url="http://zeus.test:8080",
        bucket="yelp-data",
        scope="_default",
    )
    assert r.source == "error"
    assert "zeus_headers" in (r.error or "")


@pytest.mark.asyncio
async def test_run_search_fts_and_n1ql(http_client, monkeypatch):
    zeus = "http://zeus.test:8080"
    bucket, scope, coll = "yelp-data", "_default", "_default"
    search_url = f"{zeus}/v2/{bucket}/{scope}/{coll}/search"
    pipe_url = f"{zeus}/v2/{bucket}/{scope}/{coll}/pipeline"
    n1ql_url = "http://cb.test:8093/query/service"

    fts_body = {
        "status": "ok",
        "result": {
            "src_keys": ["biz:one", "biz:two"],
            "items": [
                {"node": {"doc_key": "biz:one"}, "score": 9.0},
                {"node": {"doc_key": "biz:two"}, "score": 8.0},
            ],
        },
    }
    respx.post(search_url).mock(
        return_value=httpx.Response(200, json=fts_body, headers={"X-Zeus-Req-Id": "req-fts-1"})
    )
    # name/city pipelines return empty
    respx.post(pipe_url).mock(return_value=httpx.Response(200, json={"rows": {"rows": []}}))
    respx.post(n1ql_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "doc_key": "biz:one",
                        "name": "One Sushi",
                        "city": "Largo",
                        "state": "FL",
                        "stars": 4.0,
                        "categories": "Sushi",
                    },
                    {
                        "doc_key": "biz:two",
                        "name": "Two Rolls",
                        "city": "Largo",
                        "stars": 3.5,
                    },
                ]
            },
        )
    )

    r = await sug.run_search(
        "sushi",
        zeus_url=zeus,
        bucket=bucket,
        scope=scope,
        collection=coll,
        zeus_headers={"X-Zeus-Session": "sid"},
        couchbase=sug.CouchbaseQueryConfig(
            query_url="http://cb.test:8093",
            username="u",
            password="p",
        ),
        options=sug.SuggestOptions(use_find_name=True, use_find_city=True, limit=8),
    )
    assert r.count == 2
    assert r.hits[0].name == "One Sushi"
    assert r.hits[0].score == 9.0
    assert "zeus_fts" in r.sources
    assert "n1ql_hydrate" in r.sources
    assert r.fts_req_id == "req-fts-1"
    # FTS request body
    sent = json.loads(respx.calls[0].request.content.decode())
    assert sent["strategy"] == "fts"
    assert sent["query_text"] == "sushi"
    assert sent["entity_type"] == "Business"


@pytest.mark.asyncio
async def test_run_search_find_name_only(http_client):
    zeus = "http://zeus.test:8080"
    bucket, scope, coll = "yelp-data", "_default", "_default"
    search_url = f"{zeus}/v2/{bucket}/{scope}/{coll}/search"
    pipe_url = f"{zeus}/v2/{bucket}/{scope}/{coll}/pipeline"

    respx.post(search_url).mock(
        return_value=httpx.Response(200, json={"result": {"src_keys": [], "items": []}})
    )
    respx.post(pipe_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "rows": {
                    "rows": [
                        {
                            "id": "n_abc",
                            "name": "Pathmark",
                            "city": "Largo",
                            "stars": 3.0,
                        }
                    ]
                }
            },
        )
    )

    r = await sug.run_search(
        "Pathmark",
        zeus_url=zeus,
        bucket=bucket,
        scope=scope,
        collection=coll,
        zeus_headers={"X-Zeus-Session": "sid"},
        options=sug.SuggestOptions(
            use_fts=True,
            use_n1ql_hydrate=False,
            use_find_city=False,
        ),
    )
    assert r.count == 1
    assert r.hits[0].name == "Pathmark"
    assert "zeus_find_name" in r.sources


def test_run_fast_suggest_aliases_removed():
    """ZCM-032 / ZCP-37: deprecated nicknames are gone; use run_search*."""
    assert not hasattr(sug, "run_fast_suggest")
    assert not hasattr(sug, "run_fast_suggest_from_config")


@pytest.mark.asyncio
async def test_find_project_rows_dispatch(http_client):
    zeus = "http://zeus.test:8080"
    url = f"{zeus}/v2/yelp-data/_default/_default/pipeline"
    route = respx.post(url).mock(
        return_value=httpx.Response(
            200,
            json={"result": {"rows": [{"name": "X", "city": "Y", "doc_key": "biz:x"}]}},
        )
    )
    rows = await sug.find_project_rows(
        zeus,
        "yelp-data",
        "_default",
        "_default",
        {"X-Zeus-Session": "s"},
        {"city": "Y"},
        limit=3,
    )
    assert rows[0]["name"] == "X"
    body = json.loads(route.calls.last.request.content.decode())
    assert body["steps"][0]["tool"] == "find"
    assert body["steps"][0]["args"]["where"] == {"city": "Y"}
    assert body["steps"][1]["tool"] == "project"
