"""Expect assertion — flat dotted keys (ADAPTER_CONTRACT §4)."""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["assert_expects", "get_path"]


def get_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def assert_expects(observe: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    """Return list of diff messages (empty = pass). Unknown keys still checked."""
    diffs: list[str] = []
    for key, want in expect.items():
        if key.endswith("_gte") and isinstance(want, (int, float)):
            base = key[: -len("_gte")]
            got = observe.get(key)
            if got is None:
                got = observe.get(base)
            if got is None:
                got = get_path(observe, base)
            try:
                if float(got) < float(want):  # type: ignore[arg-type]
                    diffs.append(f"{key}: got {got!r} < {want!r}")
            except (TypeError, ValueError):
                diffs.append(f"{key}: got {got!r} not comparable to {want!r}")
            continue
        if key in observe:
            got = observe[key]
        else:
            got = get_path(observe, key)
        if got != want:
            diffs.append(f"{key}: got {got!r} want {want!r}")
    return diffs
