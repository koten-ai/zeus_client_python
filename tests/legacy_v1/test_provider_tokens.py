"""Hub-identical provider token rollup oracles (ZCP-24 / ZCP-25)."""

from __future__ import annotations

from zeus_client.trace.tokens import (
    attach_trace_tokens,
    normalize_usage,
    sum_provider_tokens,
)


def test_normalize_usage_nested_cached():
    u = normalize_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "prompt_tokens_details": {"cached_tokens": 40},
        }
    )
    assert u == {"prompt": 100, "completion": 10, "total": 110, "cached": 40}


def test_normalize_usage_top_level_cached():
    u = normalize_usage({"prompt_tokens": 5, "completion_tokens": 1, "cached_tokens": 3})
    assert u["cached"] == 3
    assert u["total"] == 0


def test_sum_multi_round_like_hub_record_ai_hop():
    steps = [
        {
            "type": "llm",
            "round": 1,
            "usage": {
                "prompt_tokens": 7800,
                "completion_tokens": 400,
                "total_tokens": 8200,
            },
        },
        {"type": "tool", "round": 1},
        {
            "type": "llm",
            "round": 2,
            "usage": {
                "prompt_tokens": 7581,
                "completion_tokens": 31,
                "total_tokens": 7612,
            },
        },
    ]
    t = sum_provider_tokens(steps=steps)
    assert t["prompt"] == 7800 + 7581
    assert t["completion"] == 400 + 31
    assert t["total"] == 8200 + 7612
    assert t["ok"] is True
    assert t["extra"] == 0


def test_tot_prefers_provider_total_even_when_gt_in_plus_out():
    steps = [
        {
            "type": "llm",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 150,
            },
        }
    ]
    t = sum_provider_tokens(steps=steps)
    assert t["total"] == 150
    assert t["extra"] == 40


def test_tot_fallback_in_plus_out_when_total_missing():
    steps = [{"type": "llm", "usage": {"prompt_tokens": 12, "completion_tokens": 8}}]
    t = sum_provider_tokens(steps=steps)
    assert t["total"] == 20
    assert t["extra"] == 0


def test_force_final_step_counted():
    steps = [
        {
            "type": "llm",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
        {
            "type": "force_final",
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 30,
                "total_tokens": 80,
            },
        },
    ]
    t = sum_provider_tokens(steps=steps)
    assert t["prompt"] == 150
    assert t["completion"] == 50
    assert t["total"] == 200


def test_fallback_ai_responses_when_step_usage_missing_no_double_count():
    steps = [
        {
            "type": "llm",
            "round": 1,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        },
        {"type": "force_final", "round": 1},  # legacy gap — no usage
    ]
    ai_responses = [
        {
            "round": 1,
            "body": {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                }
            },
        },
        {
            "round": 1,
            "force_final": True,
            "body": {
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 12,
                    "total_tokens": 52,
                }
            },
        },
    ]
    t = sum_provider_tokens(steps=steps, ai_responses=ai_responses)
    assert t["prompt"] == 50
    assert t["completion"] == 14
    assert t["total"] == 64


def test_empty_ok_false():
    t = sum_provider_tokens(steps=[{"type": "tool"}])
    assert t["ok"] is False
    assert t["prompt"] == 0
    assert t["completion"] == 0
    assert t["total"] == 0


def test_attach_trace_tokens_sets_hub_shape():
    trace = {
        "steps": [
            {
                "type": "llm",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                },
            },
            {
                "type": "force_final",
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 5,
                    "total_tokens": 10,
                },
            },
        ],
        "ai_responses": [],
    }
    out = attach_trace_tokens(trace)
    assert out is trace["tokens"]
    assert trace["tokens"]["prompt"] == 15
    assert trace["tokens"]["completion"] == 7
    assert trace["tokens"]["total"] == 22
    assert trace["tokens"]["ok"] is True
