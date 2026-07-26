"""base-5 / base-5.2 Layer A parse (ZC-WISH-004…012)."""
from zeus_client.agent.layer_a import (
    parse_layer_a,
    parse_layer_a_from_trace,
    normalize_business_rules_triggers,
    normalize_wish_i_knew,
)
from zeus_client.agent.response import extract_structured_response
from tests.fixtures.catalog_brief import base_chat_req


def test_object_triggers_sparse():
    m, present, w = normalize_business_rules_triggers(
        {"coupon_presented": True, "no_prompt_dump": False}
    )
    assert present is True
    assert m == {"coupon_presented": True, "no_prompt_dump": False}
    assert w == []


def test_array_triggers_dual_read():
    m, present, w = normalize_business_rules_triggers([False, True, True])
    assert present is True
    assert m["rule_1"] is True
    assert any("array dual-read" in x for x in w)


def test_array_triggers_rejected_when_dual_read_off():
    m, present, w = normalize_business_rules_triggers(
        [True], dual_read_arrays=False
    )
    assert m == {}
    assert present is True
    assert any("rejected" in x for x in w)


def test_wish_objects_and_legacy_string():
    items, flat, w = normalize_wish_i_knew(
        [{"what": "city", "kind": "message", "severity": "med"}]
    )
    assert items[0]["what"] == "city"
    assert flat == ["city"]

    items2, flat2, w2 = normalize_wish_i_knew("need dates")
    assert items2[0]["kind"] == "message"
    assert flat2 == ["need dates"]
    assert any("string dual-read" in x for x in w2)


def test_parse_layer_a_required_four_and_dual_gaps():
    bag = parse_layer_a(
        {
            "summary": "Found two IPAs.",
            "query_decomposition": {"intent": "list", "entity": "Beer"},
            "decomposition": {"rationale": "user asked for IPAs"},
            "confidence": "high",
            "policy_action": "answer",
            "business_rules_triggers": {},
            "wish_i_knew": [
                {"what": "price band", "kind": "schema", "severity": "low"}
            ],
            "data_gaps": [{"entity_type": "Beer", "field": "ibu"}],
        }
    )
    assert bag.required_four_ok
    assert bag.policy_action == "answer"
    assert bag.business_rules_triggers_present is True
    assert bag.business_rules_triggers == {}
    assert bag.wish_i_knew[0]["what"] == "price band"
    assert bag.data_gaps_present is True
    assert bag.data_gaps[0]["field"] == "ibu"
    assert bag.g1_answer() == "Found two IPAs."


def test_missing_required_four():
    bag = parse_layer_a({"query_decomposition": {"intent": "x", "synthetic": True}})
    assert bag.synthetic is True
    assert "summary" in bag.missing_required
    assert "confidence" in bag.missing_required
    assert not bag.required_four_ok


def test_extract_structured_response_attaches_layer_a():
    trace = {
        "steps": [
            {
                "type": "return",
                "args": {
                    "summary": "OK beers",
                    "query_decomposition": {
                        "intent": "list",
                        "entity": "Beer",
                    },
                    "decomposition": {"text": "listed"},
                    "confidence": "med",
                    "business_rules_triggers": {"vip": True},
                    "data_gaps": [],
                },
            }
        ],
        "tool_calls": [],
    }
    resp = extract_structured_response("", trace, base_chat_req())
    assert resp.answer == "OK beers"  # G1 from summary when answer empty
    assert resp.layer_a is not None
    assert resp.layer_a.required_four_ok
    assert resp.layer_a.business_rules_triggers["vip"] is True
    assert resp.layer_a.data_gaps_present is True
    assert resp.layer_a.data_gaps == []


def test_parse_from_trace():
    bag = parse_layer_a_from_trace(
        {
            "steps": [
                {"type": "tool", "args": {}},
                {
                    "type": "return",
                    "args": {
                        "summary": "hi",
                        "query_decomposition": {"intent": "a", "entity": "b"},
                        "decomposition": {},
                        "confidence": "low",
                    },
                },
            ]
        }
    )
    assert bag.summary == "hi"
    assert bag.required_four_ok
