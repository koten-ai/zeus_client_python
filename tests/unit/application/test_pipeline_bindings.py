"""FTS pipeline @step.ids is rewritten to @step.doc_keys before Zeus."""

from __future__ import annotations

from zeus_client.domain.pipeline_bindings import rewrite_fts_ids_to_doc_keys


def _peach():
    return {
        "steps": [
            {
                "as": "peach_beers",
                "verb": "search",
                "entity_type": "Beer",
                "strategy": "fts",
                "query_text": "peach",
            },
            {
                "as": "ranked",
                "verb": "project",
                "ids": "@peach_beers.ids",
                "fields": ["name", "style"],
            },
        ],
        "summary": "keep @peach_beers.ids in the summary",
    }


def test_fts_project_ids_become_doc_keys() -> None:
    body, changed = rewrite_fts_ids_to_doc_keys(_peach())
    assert changed == ("peach_beers",)
    assert body["steps"][1]["ids"] == "@peach_beers.doc_keys"
    assert body["summary"] == "keep @peach_beers.ids in the summary"
    assert body["steps"][0]["strategy"] == "fts"


def test_order_passthrough_rewrites_the_next_ids() -> None:
    body = {
        "steps": [
            {"as": "peach_beers", "verb": "search", "strategy": "fts", "query_text": "peach"},
            {"as": "ranked", "verb": "order", "ids": "@peach_beers.ids", "by": "id"},
            {"as": "rows", "verb": "project", "ids": "@ranked.ids", "fields": ["name"]},
        ]
    }
    out, changed = rewrite_fts_ids_to_doc_keys(body)
    assert changed == ("peach_beers", "ranked")
    assert out["steps"][1]["ids"] == "@peach_beers.doc_keys"
    assert out["steps"][2]["ids"] == "@ranked.doc_keys"


def test_hybrid_ids_stay() -> None:
    body = {
        "steps": [
            {"as": "hits", "verb": "search", "strategy": "hybrid", "query_text": "peach"},
            {"as": "ranked", "verb": "project", "ids": "@hits.ids"},
        ]
    }
    out, changed = rewrite_fts_ids_to_doc_keys(body)
    assert changed == ()
    assert out["steps"][1]["ids"] == "@hits.ids"


def test_node_ids_and_doc_keys_stay() -> None:
    body = {
        "steps": [
            {"as": "hits", "verb": "search", "strategy": "fts", "query_text": "peach"},
            {
                "as": "ranked",
                "verb": "project",
                "ids": "@hits.node_ids",
                "src_keys": "@hits.doc_keys",
            },
        ]
    }
    out, changed = rewrite_fts_ids_to_doc_keys(body)
    assert changed == ()
    assert out["steps"][1]["ids"] == "@hits.node_ids"
    assert out["steps"][1]["src_keys"] == "@hits.doc_keys"


def test_nested_params_and_longer_step_name() -> None:
    body = {
        "steps": [
            {"as": "peach", "verb": "search", "strategy": "fts", "query_text": "peach"},
            {"as": "peach_beers", "verb": "search", "strategy": "fts", "query_text": "peach"},
            {"verb": "project", "params": {"ids": ["@peach.ids", "@peach_beers.ids"]}},
        ]
    }
    out, changed = rewrite_fts_ids_to_doc_keys(body)
    assert set(changed) == {"peach", "peach_beers"}
    assert out["steps"][2]["params"]["ids"] == [
        "@peach.doc_keys",
        "@peach_beers.doc_keys",
    ]


def test_strategy_inside_params() -> None:
    body = {
        "steps": [
            {"as": "hits", "verb": "search", "params": {"strategy": "fts", "query_text": "peach"}},
            {"as": "rows", "verb": "project", "ids": "@hits.ids"},
        ]
    }
    out, changed = rewrite_fts_ids_to_doc_keys(body)
    assert changed == ("hits",)
    assert out["steps"][1]["ids"] == "@hits.doc_keys"


def test_no_steps_is_unchanged() -> None:
    body = {"summary": "hi"}
    out, changed = rewrite_fts_ids_to_doc_keys(body)
    assert changed == ()
    assert out == body
