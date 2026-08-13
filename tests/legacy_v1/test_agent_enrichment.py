"""Tests for python3/agent/enrichment.py — tool result amplification."""
import json

import pytest

from zeus_client.agent.enrichment import amplify_tool_content


def test_search_non_200_adds_problem_note():
    body = json.dumps({"result": {"returned_count": 5}})
    out = amplify_tool_content("search", 500, body, body)
    assert "[ZEUS RECALL NOTE" in out
    assert "error/timeout/zero" in out
    assert out.endswith(body) or body in out


def test_search_error_field_adds_problem_note():
    body = json.dumps({"error": "timeout", "result": {"returned_count": 1}})
    out = amplify_tool_content("search", 200, body, body)
    assert "error/timeout/zero" in out


def test_search_zero_results_adds_problem_note():
    body = json.dumps({"result": {"returned_count": 0}})
    out = amplify_tool_content("search", 200, body, body)
    assert "error/timeout/zero" in out


def test_search_hints_prepended():
    body = json.dumps({
        "result": {"returned_count": 1},
        "input_hints": [
            {"suggested": "fts:beer", "message": "try broader", "code": "LOW_RECALL"},
        ],
    })
    out = amplify_tool_content("search", 200, body, body)
    assert "fts:beer" in out
    assert "try broader" in out
    assert "LOW_RECALL" in out


def test_search_invalid_json_without_hints_unchanged():
    """Invalid JSON yields empty parse; no problem signal without error/zero count."""
    out = amplify_tool_content("search", 200, "not-json", "not-json")
    assert out == "not-json"


def test_search_invalid_json_with_error_status():
    out = amplify_tool_content("search", 500, "not-json", "not-json")
    assert "[ZEUS RECALL NOTE" in out
    assert "error/timeout/zero" in out


def test_search_ok_no_hints_unchanged():
    body = json.dumps({"result": {"returned_count": 3}})
    out = amplify_tool_content("search", 200, body, body)
    assert out == body


def test_find_with_ids_prepends_guidance():
    body = json.dumps({"result": {"items": [{"id": "n_1"}, {"id": "n_2"}, {"no_id": True}]}})
    out = amplify_tool_content("find", 200, body, body)
    assert "USE THESE IDS FOR ALL FOLLOW-UP" in out
    assert "n_1" in out
    assert "n_2" in out


def test_find_no_ids_unchanged():
    body = json.dumps({"result": {"items": [{"name": "x"}]}})
    out = amplify_tool_content("find", 200, body, body)
    assert out == body


def test_find_invalid_json_unchanged():
    out = amplify_tool_content("find", 200, "bad", "bad")
    assert out == "bad"


def test_get_partial_status_adds_correction():
    body = json.dumps({"status": "partial", "result": {"missing_node_ids": ["wrong"]}})
    out = amplify_tool_content("get", 200, body, body)
    assert "[ZEUS GET ID CORRECTION" in out
    assert "wrong" in out


def test_get_zero_returned_count_adds_correction():
    body = json.dumps({"result": {"returned_count": 0}})
    out = amplify_tool_content("get", 200, body, body)
    assert "[ZEUS GET ID CORRECTION" in out


def test_get_missing_node_ids_adds_correction():
    body = json.dumps({"result": {"missing_node_ids": ["n_bad"], "returned_count": 1}})
    out = amplify_tool_content("get", 200, body, body)
    assert "n_bad" in out


def test_get_ok_unchanged():
    body = json.dumps({"result": {"returned_count": 2}})
    out = amplify_tool_content("get", 200, body, body)
    assert out == body


def test_other_tool_name_unchanged():
    out = amplify_tool_content("pipeline", 200, "{}", "{}")
    assert out == "{}"


def test_search_hints_skips_non_dict_and_empty_keys():
    body = json.dumps({
        "result": {"returned_count": 1},
        "input_hints": ["bad", {"message": "", "suggested": "fts:beer"}],
    })
    out = amplify_tool_content("search", 200, body, body)
    assert "fts:beer" in out


def test_get_invalid_json_unchanged():
    out = amplify_tool_content("get", 200, "not-json", "raw-content")
    assert out == "raw-content"