"""Load response_output_schema.json for the same base_id as a catalog file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["load_sibling_pack_schema"]

_SCHEMA_NAMES = (
    "response_output_schema.json",
    "response_output_schema.min.json",
)
_EXAMPLE_NAMES = (
    "response_output_example.json",
    "response_output_example.min.json",
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_sibling_pack_schema(catalog_path: str | Path | None) -> tuple[dict | None, dict | None]:
    """Return (schema, example) from the catalog file's directory."""
    if not catalog_path:
        return None, None
    parent = Path(catalog_path).parent
    schema: dict[str, Any] | None = None
    example: dict[str, Any] | None = None
    for name in _SCHEMA_NAMES:
        p = parent / name
        if p.is_file():
            schema = _read_json(p)
            if schema is not None:
                break
    for name in _EXAMPLE_NAMES:
        p = parent / name
        if p.is_file():
            example = _read_json(p)
            if example is not None:
                break
    return schema, example
