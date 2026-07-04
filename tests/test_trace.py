"""Trace pipeline spans."""
import json

from zeus_client.trace.pipeline import _pipeline_step_costs as pipeline_step_costs
from zeus_client.trace.pipeline import pipeline_step_spans


def test_pipeline_step_spans_ignores_non_dict_steps():
    parsed = {"meta": {"step_costs": [{"as": "s1", "ms": 5}]}}
    tc_args = {"steps": ["bad", {"verb": "find"}, {"name": "s1", "verb": "get"}]}
    spans = pipeline_step_spans(0, 5, tc_args, parsed)
    assert spans[0]["verb"] == "get"


def test_pipeline_step_spans_fallback_single_span():
    spans = pipeline_step_spans(1000, 250, None, None)
    assert spans == [{"name": "tool.pipeline", "cls": "tool", "at": 1000, "ms": 250}]


def test_pipeline_step_spans_step_name_fallback_and_no_detail():
    parsed = {"meta": {"step_costs": [{"name": "stepx", "ms": 10}]}}
    spans = pipeline_step_spans(0, 10, {"steps": [{"as": "stepx", "verb": "find"}]}, parsed)
    assert spans[0]["name"] == "pipeline.stepx.find"
    assert spans[0]["detail"] is None


def test_pipeline_step_spans_with_costs_and_overhead():
    parsed = {
        "meta": {
            "step_costs": [
                {"as": "s1", "ms": 40, "cost": 1, "result_size": 3, "status": "ok"},
                {"name": "s2", "ms": 30, "status": "planned"},
            ],
        },
    }
    tc_args = {"steps": [{"name": "s1", "verb": "find"}, {"as": "s2", "verb": "get"}]}
    spans = pipeline_step_spans(100, 100, tc_args, parsed)
    assert len(spans) == 3
    assert spans[0]["name"] == "pipeline.s1.find"
    assert spans[0]["detail"] == "cost 1 · 3 rows · ok"
    assert spans[1]["name"] == "pipeline.s2.get"
    assert spans[1]["detail"] == "planned"
    assert spans[2]["name"] == "pipeline.overhead"
    assert spans[2]["ms"] == 30


def test_pipeline_step_spans_no_overhead_when_zero():
    parsed = {"meta": {"step_costs": [{"as": "only", "ms": 50}]}}
    spans = pipeline_step_spans(0, 50, {}, parsed)
    assert len(spans) == 1
    assert spans[0]["verb"] is None


def test_pipeline_py_step_costs_branches():
    step = {"pipeline_step_costs": [{"as": "a", "ms": 1}]}
    assert pipeline_step_costs(step) == [{"as": "a", "ms": 1}]

    body = json.dumps({"meta": {"step_costs": [{"as": "b", "ms": 2}]}})
    assert pipeline_step_costs({"result_full": body})[0]["as"] == "b"

    assert pipeline_step_costs({"result": "not-json"}) == []
    assert pipeline_step_costs({
        "name": "pipeline",
        "result": json.dumps({"status": "error"}),
    }) == [{"status": "error"}]

    plan = {"args": {"steps": [{"name": "x"}, "bad", {"name": "y"}]}}
    costs = pipeline_step_costs(plan)
    assert costs == [{"as": "x", "status": "planned"}, {"as": "y", "status": "planned"}]


def test_pipeline_step_costs_ok_status_skips_error_branch():
    raw = json.dumps({"status": "ok", "meta": {"step_costs": []}})
    assert pipeline_step_costs({"name": "pipeline", "result": raw}) == []