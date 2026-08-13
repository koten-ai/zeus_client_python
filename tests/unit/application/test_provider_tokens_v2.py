"""V2 dual-tree oracles — identical numbers to tests/test_provider_tokens.py (ZCP-28)."""
from __future__ import annotations

from zeus_client_v2.application.tokens import (
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
        {"type": "force_final", "round": 1},
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
    assert trace["tokens"]["total"] == 22
