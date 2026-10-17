"""ZCP-127 — OpenAI rejects stock catalog tool schemas that have no type."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from zeus_client.adapters.llm_openai_compatible import build_chat_payload

_NARROW = "Pipeline-only id-list allow-list; direct id list or @step binding."
_WHY = "Accepted but no-op outside a pipeline."
_FIND_NARROW: dict[str, Any] = {
    "description": _NARROW,
    "oneOf": [
        {"type": "array", "items": {"type": "string"}},
        {"type": "string"},
    ],
}
_ID_OR_OBJECT: dict[str, Any] = {
    "anyOf": [
        {"type": "string"},
        {"type": "object", "additionalProperties": True},
    ]
}

_CHAT_REQUESTS = (
    Path(__file__).resolve().parents[4] / "demo_travel_sample" / "data" / "chat_requests"
)
_SHIPPED = [
    _CHAT_REQUESTS / "travel-sample__default" / "chat_request_analytics_v2.json",
    _CHAT_REQUESTS / "chat_request_analytics_base-6.1.json",
]


def _fn(name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "parameters": parameters}}


def _stock_tools() -> list[dict[str, Any]]:
    """Shapes named in ZCP-127, including the base-6.1 boolean map."""
    return [
        _fn(
            "find",
            {
                "type": "object",
                "properties": {
                    "where": {"type": "object", "additionalProperties": True},
                    "narrow_to": copy.deepcopy(_FIND_NARROW),
                },
            },
        ),
        _fn(
            "traverse",
            {
                "type": "object",
                "properties": {"narrow_to": {"description": _NARROW}},
            },
        ),
        _fn(
            "search",
            {
                "type": "object",
                "examples": [
                    {
                        "strategy": "fts",
                        "query_text": "beach",
                        "entity_type": "landmark",
                    }
                ],
                "properties": {"narrow_to": {"description": _NARROW}},
            },
        ),
        _fn(
            "analyze",
            {"type": "object", "properties": {"narrow_to": {"description": _NARROW}}},
        ),
        _fn(
            "set",
            {
                "type": "object",
                "properties": {
                    "inputs": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 8,
                        "items": {"type": "array"},
                    }
                },
            },
        ),
        _fn(
            "order",
            {"type": "object", "properties": {"ids": {"type": "array", "items": {}}}},
        ),
        _fn(
            "enrich",
            {"type": "object", "properties": {"ids": {"type": "array", "items": {}}}},
        ),
        _fn(
            "project",
            {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {}},
                    "why_match_from": {"description": _WHY},
                },
            },
        ),
        _fn(
            "pipeline",
            {
                "type": "object",
                "properties": {
                    "entity_refs": {"type": "array", "items": {}},
                    "node_refs": {"type": "array", "items": {}},
                    "provenance": {"type": "array", "items": {}},
                },
            },
        ),
        _fn(
            "return",
            {
                "type": "object",
                "properties": {
                    "entity_refs": {"type": "array", "items": {}},
                    "node_refs": {"type": "array", "items": {}},
                    "provenance": {"type": "array", "items": {}},
                    "business_rules_triggers": {
                        "type": "object",
                        "additionalProperties": {"type": "boolean"},
                    },
                },
            },
        ),
    ]


def _props(tools: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for tool in tools:
        function = tool["function"]
        if function["name"] == name:
            return function["parameters"]["properties"]
    raise AssertionError(name)


def test_stock_catalog_shapes_repair_without_strict_or_mutation() -> None:
    original = _stock_tools()
    snapshot = copy.deepcopy(original)
    payload = build_chat_payload(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "beaches in California"}],
        tools=original,
    )
    assert original == snapshot
    assert payload["tool_choice"] == "auto"
    assert "strict" not in payload
    tools = payload["tools"]
    assert schema_issues(tools) == []

    for tool in tools:
        assert "strict" not in tool
        assert "strict" not in tool["function"]

    assert _props(tools, "find")["narrow_to"] == _FIND_NARROW
    assert _props(tools, "find")["where"]["additionalProperties"] is True
    for name in ("traverse", "search", "analyze"):
        assert _props(tools, name)["narrow_to"]["description"] == _NARROW
        assert _props(tools, name)["narrow_to"]["oneOf"] == _FIND_NARROW["oneOf"]

    search_params = next(
        t["function"]["parameters"] for t in tools if t["function"]["name"] == "search"
    )
    assert search_params["examples"] == snapshot[2]["function"]["parameters"]["examples"]
    assert "type" not in search_params["examples"][0]

    inputs = _props(tools, "set")["inputs"]
    assert inputs["minItems"] == 2
    assert inputs["items"]["type"] == "array"
    assert inputs["items"]["items"] == _ID_OR_OBJECT

    for name in ("order", "enrich", "project"):
        assert _props(tools, name)["ids"]["items"] == _ID_OR_OBJECT
    assert _props(tools, "project")["why_match_from"] == {
        "description": _WHY,
        "type": "string",
    }
    for name in ("pipeline", "return"):
        props = _props(tools, name)
        for field in ("entity_refs", "node_refs", "provenance"):
            assert props[field]["items"] == _ID_OR_OBJECT
    triggers = _props(tools, "return")["business_rules_triggers"]
    assert triggers["additionalProperties"] == {"type": "boolean"}
    assert triggers["type"] == "object"

    again = build_chat_payload(model="gpt-4o-mini", messages=[], tools=tools)
    assert again["tools"] == tools


def test_parameterless_tool_is_unchanged_and_nested_input_is_not_shared() -> None:
    tool = {"type": "function", "function": {"name": "find"}}
    payload = build_chat_payload(model="m", messages=[], tools=[tool])
    assert payload["tools"] == [tool]
    assert "strict" not in payload["tools"][0]

    live = _fn("order", {"type": "object", "properties": {"ids": {"type": "array", "items": {}}}})
    items = live["function"]["parameters"]["properties"]["ids"]["items"]
    repaired = build_chat_payload(model="m", messages=[], tools=[live])
    assert items == {}
    assert repaired["tools"][0]["function"]["parameters"] is not live["function"]["parameters"]


def test_structural_gaps_get_a_type_without_rewriting_anchors() -> None:
    tools = [
        _fn("empty", {}),
        _fn("obj", {"properties": {"q": {"type": "string"}}}),
        _fn("bare_array", {"minItems": 1}),
        _fn("nested", {"type": "array"}),
        _fn("ref", {"$ref": "#/$defs/Node", "description": "keep"}),
        _fn("prefix", {"prefixItems": [{"type": "string"}]}),
        _fn("flag", {"const": False}),
        _fn("count", {"const": 2}),
        _fn("when", {"format": "date-time"}),
        _fn("floor", {"minimum": 0}),
        _fn("choice", {"enum": ["a", "b"]}),
        _fn("mixed", {"enum": ["a", 1], "description": "either"}),
        _fn("free_map", {"additionalProperties": {}}),
    ]
    odd = {"type": "function", "function": {"name": "odd", "parameters": ["nope"]}}
    payload = build_chat_payload(model="m", messages=[], tools=[*tools, odd])
    by_name = {
        tool["function"]["name"]: tool["function"]["parameters"] for tool in payload["tools"]
    }

    assert by_name["empty"] == {"type": "object"}
    assert by_name["obj"]["type"] == "object"
    assert by_name["obj"]["properties"]["q"] == {"type": "string"}
    assert by_name["bare_array"]["type"] == "array"
    assert by_name["bare_array"]["items"] == _ID_OR_OBJECT
    assert by_name["nested"] == {"type": "array", "items": _ID_OR_OBJECT}
    assert by_name["ref"] == {"$ref": "#/$defs/Node", "description": "keep"}
    assert by_name["prefix"]["type"] == "array"
    assert "items" not in by_name["prefix"]
    assert by_name["prefix"]["prefixItems"] == [{"type": "string"}]
    assert by_name["flag"] == {"const": False, "type": "boolean"}
    assert by_name["count"] == {"const": 2, "type": "integer"}
    assert by_name["when"] == {"format": "date-time", "type": "string"}
    assert by_name["floor"] == {"minimum": 0, "type": "number"}
    assert by_name["choice"] == {"enum": ["a", "b"], "type": "string"}
    assert by_name["mixed"]["description"] == "either"
    assert by_name["mixed"]["anyOf"] == [
        {"type": "string", "enum": ["a"]},
        {"type": "integer", "enum": [1]},
    ]
    free = by_name["free_map"]["additionalProperties"]
    assert free["anyOf"][0] == {"type": "string"}
    assert {"type": "boolean"} in free["anyOf"]
    assert any(branch.get("type") == "array" for branch in free["anyOf"])
    assert by_name["odd"] == ["nope"]
    assert schema_issues(payload["tools"]) == []


def test_tuple_items_unions_and_contains_are_anchored() -> None:
    payload = build_chat_payload(
        model="m",
        messages=[],
        tools=[
            _fn("union", {"type": ["string", "null"]}),
            _fn(
                "tuple",
                {
                    "type": "array",
                    "items": [{"description": _NARROW}, {"type": "number"}],
                },
            ),
            _fn(
                "box",
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "contains": {"description": _WHY},
                    "const": None,
                },
            ),
            _fn("pi", {"const": 1.5}),
            _fn("bag", {"const": {"id": "n1"}}),
            _fn("row", {"const": ["n1"]}),
        ],
    )
    by_name = {
        tool["function"]["name"]: tool["function"]["parameters"] for tool in payload["tools"]
    }
    assert by_name["union"] == {"type": ["string", "null"]}
    assert by_name["tuple"]["items"][0]["description"] == _NARROW
    assert by_name["tuple"]["items"][0]["anyOf"] == _ID_OR_OBJECT["anyOf"]
    assert by_name["tuple"]["items"][1] == {"type": "number"}
    assert by_name["box"]["contains"] == {"description": _WHY, "type": "string"}
    assert by_name["box"]["const"] is None
    assert by_name["box"]["type"] == "array"
    assert by_name["pi"] == {"const": 1.5, "type": "number"}
    assert by_name["bag"] == {"const": {"id": "n1"}, "type": "object"}
    assert by_name["row"] == {"const": ["n1"], "type": "array", "items": _ID_OR_OBJECT}
    assert schema_issues(payload["tools"]) == []


def schema_issues(tools: list[dict[str, Any]]) -> list[str]:
    """OpenAI non-strict rule from ZCP-127: every schema node has a type or combinator."""
    found: list[str] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if not isinstance(function, dict):
            continue
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            _walk_schema(parameters, f"{function.get('name', '?')}.parameters", found)
    return found


def _walk_schema(node: Any, path: str, found: list[str]) -> None:
    if isinstance(node, bool) or not isinstance(node, dict):
        return
    if not _anchored(node):
        found.append(path)
    types = _types_of(node)
    if "array" in types and "items" not in node and "prefixItems" not in node:
        found.append(f"{path} ARRAY_NO_ITEMS")
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        child = node.get(key)
        if isinstance(child, dict):
            for name, sub in child.items():
                _walk_schema(sub, f"{path}.{key}.{name}", found)
    for key in (
        "additionalProperties",
        "unevaluatedProperties",
        "additionalItems",
        "unevaluatedItems",
        "contains",
        "propertyNames",
        "if",
        "then",
        "else",
        "not",
        "items",
    ):
        if key not in node:
            continue
        value = node[key]
        if isinstance(value, list) and key == "items":
            for index, sub in enumerate(value):
                _walk_schema(sub, f"{path}.items[{index}]", found)
        else:
            _walk_schema(value, f"{path}.{key}", found)
    for key in ("oneOf", "anyOf", "allOf", "prefixItems"):
        value = node.get(key)
        if isinstance(value, list):
            for index, sub in enumerate(value):
                _walk_schema(sub, f"{path}.{key}[{index}]", found)


def _anchored(node: dict[str, Any]) -> bool:
    if isinstance(node.get("$ref"), str) and node["$ref"]:
        return True
    for key in ("oneOf", "anyOf", "allOf"):
        value = node.get(key)
        if isinstance(value, list) and value:
            return True
    return bool(_types_of(node))


def _types_of(node: dict[str, Any]) -> set[str]:
    raw = node.get("type")
    if isinstance(raw, str) and raw:
        return {raw}
    if isinstance(raw, list):
        return {item for item in raw if isinstance(item, str) and item}
    return set()


@pytest.mark.skipif(
    not _CHAT_REQUESTS.is_dir(),
    reason="demo_travel_sample catalog is not checked out beside this repo",
)
@pytest.mark.parametrize("path", _SHIPPED, ids=lambda path: path.name)
def test_shipped_travel_catalog_repairs_clean(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    verbs = document["verbs"]
    before = copy.deepcopy(verbs)
    assert schema_issues(verbs), path.name
    payload = build_chat_payload(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "beaches"}],
        tools=verbs,
    )
    assert verbs == before
    assert schema_issues(payload["tools"]) == []
    before_by_name = {verb["function"]["name"]: verb for verb in before}
    for tool in payload["tools"]:
        assert "strict" not in tool
        function = tool["function"]
        assert "strict" not in function
        old_params = before_by_name[function["name"]]["function"]["parameters"]
        if "examples" in old_params:
            assert function["parameters"]["examples"] == old_params["examples"]
    triggers = _props(payload["tools"], "return").get("business_rules_triggers")
    if isinstance(triggers, dict):
        assert triggers["additionalProperties"] == {"type": "boolean"}
