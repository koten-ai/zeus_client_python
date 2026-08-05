"""Layer A harvest for session_trace / Detective join."""
from zeus_client.agent.response import layer_a_for_session_trace, _parse_return_payload


def test_parse_return_result_step():
    trace = {
        "steps": [
            {"type": "tool", "name": "find", "args": {"entity_type": "Business"}},
            {
                "type": "return_result",
                "args": {
                    "summary": "ok",
                    "query_decomposition": {"intent": "List", "entity": "Business"},
                    "decomposition": {"targets": ["Business"]},
                    "confidence": "high",
                },
            },
        ]
    }
    p = _parse_return_payload(trace)
    assert p["confidence"] == "high"
    la = layer_a_for_session_trace(trace)
    assert la["intent"] == "List"
    assert la["query_decomposition"]["entity"] == "Business"
    assert la["via"] == "client_terminate"


def test_parse_terminating_pipeline_tool_step():
    trace = {
        "steps": [
            {
                "type": "tool",
                "name": "pipeline",
                "args": {
                    "summary": "found",
                    "turn_complete": True,
                    "query_decomposition": {"intent": "Count", "entity": "Review"},
                    "decomposition": {"targets": ["Review"]},
                    "confidence": "med",
                    "steps": [{"as": "a", "verb": "find"}],
                },
            }
        ]
    }
    la = layer_a_for_session_trace(trace)
    assert la["intent"] == "Count"
    assert la["confidence"] == "med"
    assert la["summary"] == "found"


def test_empty_trace():
    assert layer_a_for_session_trace({}) == {}
    assert layer_a_for_session_trace(None) == {}
