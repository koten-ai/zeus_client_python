"""Make stock Zeus tool schemas acceptable to OpenAI Chat Completions (ZCP-127).

OpenAI's non-strict function validator still requires every schema object to
carry ``type`` or ``oneOf`` / ``anyOf`` / ``allOf`` / ``$ref``, and every array
to carry ``items``. Stock analytics verbs omit those on ``narrow_to``,
``why_match_from``, empty ``items: {}``, and ``set.inputs`` inner arrays.
xAI accepts the looser documents. ``strict`` stays unset: the same catalogs use
``additionalProperties: true`` and ``additionalProperties: {type: boolean}``,
which strict mode rejects.

The repair deep-copies. Callers keep the catalog they loaded, including any
contract hash over that document.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["repair_openai_tool_schemas"]

_ANNOTATIONS = ("description", "title", "default", "examples", "example", "deprecated")
_ARRAY_HINTS = (
    "items",
    "prefixItems",
    "additionalItems",
    "unevaluatedItems",
    "contains",
    "minItems",
    "maxItems",
    "uniqueItems",
)
_OBJECT_HINTS = (
    "properties",
    "patternProperties",
    "additionalProperties",
    "unevaluatedProperties",
    "required",
)
_STRING_HINTS = ("minLength", "maxLength", "pattern", "format")
_NUMBER_HINTS = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
)
_SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
_SCHEMA_NODES = (
    "additionalItems",
    "unevaluatedItems",
    "contains",
    "propertyNames",
    "if",
    "then",
    "else",
    "not",
)
_SCHEMA_LISTS = ("oneOf", "anyOf", "allOf", "prefixItems")


def repair_openai_tool_schemas(tools: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return OpenAI-safe copies of function tools. Input mappings are not mutated."""
    repaired: list[dict[str, Any]] = []
    for tool in tools:
        copied: dict[str, Any] = copy.deepcopy(dict(tool))
        _repair_tool(copied)
        repaired.append(copied)
    return repaired


def _repair_tool(tool: dict[str, Any]) -> None:
    function = tool.get("function")
    target = function if isinstance(function, dict) else tool
    parameters = target.get("parameters")
    if isinstance(parameters, dict):
        _repair_schema(parameters, role="root")


def _repair_schema(schema: Any, *, role: str) -> None:
    if not isinstance(schema, dict):
        return
    if not _has_anchor(schema):
        inferred = _inferred_type(schema)
        if inferred is not None:
            schema["type"] = inferred
        elif _split_mixed_enum(schema):
            pass
        elif role == "items":
            _become(schema, _id_or_object_schema())
        elif role in ("additionalProperties", "unevaluatedProperties"):
            _become(schema, _any_json_schema())
        elif _is_id_list_text(schema.get("description")):
            schema["oneOf"] = [
                {"type": "array", "items": {"type": "string"}},
                {"type": "string"},
            ]
        elif role == "root":
            schema["type"] = "object"
        else:
            schema["type"] = "string"
    if "array" in _type_names(schema) and "items" not in schema and "prefixItems" not in schema:
        schema["items"] = _id_or_object_schema()
    _walk(schema)


def _walk(schema: dict[str, Any]) -> None:
    for key in _SCHEMA_MAPS:
        child = schema.get(key)
        if isinstance(child, dict):
            for sub in child.values():
                _repair_schema(sub, role="property")
    for key in ("additionalProperties", "unevaluatedProperties"):
        if key in schema:
            _repair_schema(schema[key], role=key)
    for key in _SCHEMA_NODES:
        if key in schema:
            _repair_schema(schema[key], role="property")
    items = schema.get("items")
    if isinstance(items, dict):
        _repair_schema(items, role="items")
    elif isinstance(items, list):
        for sub in items:
            _repair_schema(sub, role="items")
    for key in _SCHEMA_LISTS:
        child = schema.get(key)
        if isinstance(child, list):
            for sub in child:
                _repair_schema(sub, role="property")


def _has_anchor(schema: dict[str, Any]) -> bool:
    if isinstance(schema.get("$ref"), str) and schema["$ref"]:
        return True
    for key in ("oneOf", "anyOf", "allOf"):
        value = schema.get(key)
        if isinstance(value, list) and value:
            return True
    return bool(_type_names(schema))


def _type_names(schema: dict[str, Any]) -> set[str]:
    raw = schema.get("type")
    if isinstance(raw, str) and raw:
        return {raw}
    if isinstance(raw, list):
        return {item for item in raw if isinstance(item, str) and item}
    return set()


def _inferred_type(schema: dict[str, Any]) -> str | None:
    if any(key in schema for key in _ARRAY_HINTS):
        return "array"
    if any(key in schema for key in _OBJECT_HINTS):
        return "object"
    if any(key in schema for key in _STRING_HINTS):
        return "string"
    if any(key in schema for key in _NUMBER_HINTS):
        return "number"
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        kinds = {kind for kind in (_json_kind(value) for value in enum) if kind is not None}
        if len(kinds) == 1:
            return next(iter(kinds))
        return None
    if "const" in schema:
        return _json_kind(schema["const"])
    return None


def _json_kind(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return None


def _split_mixed_enum(schema: dict[str, Any]) -> bool:
    """A mixed ``enum`` with no ``type`` becomes ``anyOf`` branches OpenAI can read."""
    enum = schema.get("enum")
    if not isinstance(enum, list) or not enum:
        return False
    grouped: dict[str, list[Any]] = {}
    for value in enum:
        kind = _json_kind(value)
        if kind is None:
            continue
        grouped.setdefault(kind, []).append(value)
    if len(grouped) <= 1:
        return False
    _become(schema, {"anyOf": [{"type": kind, "enum": values} for kind, values in grouped.items()]})
    return True


def _is_id_list_text(description: Any) -> bool:
    if not isinstance(description, str):
        return False
    text = description.lower()
    return "id-list" in text or "id list" in text


def _become(schema: dict[str, Any], fresh: dict[str, Any]) -> None:
    kept = {key: schema[key] for key in _ANNOTATIONS if key in schema}
    schema.clear()
    schema.update(fresh)
    schema.update(kept)


def _id_or_object_schema() -> dict[str, Any]:
    """Bare ids or scored / ref objects. Stock catalogs leave ``items`` as ``{}``."""
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "object", "additionalProperties": True},
        ]
    }


def _scalar_schemas() -> list[dict[str, Any]]:
    return [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "object", "additionalProperties": True},
    ]


def _any_json_schema() -> dict[str, Any]:
    """Unconstrained map values. One array level, each node anchored."""
    return {
        "anyOf": [
            *_scalar_schemas(),
            {"type": "array", "items": {"anyOf": _scalar_schemas()}},
        ]
    }
