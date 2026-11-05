"""FTS pipeline bindings.

@step.ids is node ids only. An fts search leaves that list empty, so a later
project of @step.ids returns no rows. The hit list is @step.doc_keys.

order and set copy those source keys onto their own doc_keys list and leave
node_ids empty. A following @that.ids is the same miss, so the rewrite
follows the keys through those steps.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_PASSTHROUGH = frozenset({"order", "set"})


def _strategy(step: Mapping[str, Any]) -> str:
    strategy = step.get("strategy")
    params = step.get("params")
    if strategy in (None, "") and isinstance(params, Mapping):
        strategy = params.get("strategy")
    return str(strategy or "").strip().lower()


def _fts_step_names(steps: list[Any]) -> list[str]:
    names: list[str] = []
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if str(step.get("verb") or "").strip().lower() != "search":
            continue
        if _strategy(step) != "fts":
            continue
        name = str(step.get("as") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _pattern(names: set[str]) -> re.Pattern[str] | None:
    if not names:
        return None
    ordered = sorted(names, key=len, reverse=True)
    return re.compile(r"@(" + "|".join(re.escape(name) for name in ordered) + r")\.ids\b")


def rewrite_fts_ids_to_doc_keys(
    body: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return a pipeline body whose later steps bind FTS hits as doc_keys.

    Hybrid, vector, and find steps are left alone. @step.node_ids and an
    existing @step.doc_keys binding are left alone. The returned names are
    the steps whose @step.ids token was rewritten.
    """
    if not isinstance(body, Mapping):
        return {}, ()
    raw_steps = body.get("steps")
    if not isinstance(raw_steps, list):
        return dict(body), ()
    producers = set(_fts_step_names(raw_steps))
    if not producers:
        return dict(body), ()
    changed: list[str] = []

    def rewrite(value: Any, pattern: re.Pattern[str]) -> Any:
        if isinstance(value, str):

            def sub(match: re.Match[str]) -> str:
                step = match.group(1)
                if step not in changed:
                    changed.append(step)
                return f"@{step}.doc_keys"

            return pattern.sub(sub, value)
        if isinstance(value, list):
            return [rewrite(item, pattern) for item in value]
        if isinstance(value, dict):
            return {key: rewrite(item, pattern) for key, item in value.items()}
        return value

    new_steps: list[Any] = []
    for step in raw_steps:
        pattern = _pattern(producers)
        if not isinstance(step, Mapping) or pattern is None:
            new_steps.append(step)
            continue
        rewritten = rewrite(dict(step), pattern)
        new_steps.append(rewritten)
        verb = str(step.get("verb") or "").strip().lower()
        name = str(step.get("as") or "").strip()
        if verb in _PASSTHROUGH and name and isinstance(rewritten, dict):
            blob = _text_blob(rewritten)
            if any(f"@{producer}.doc_keys" in blob for producer in producers):
                producers.add(name)
    if not changed:
        return dict(body), ()
    out = dict(body)
    out["steps"] = new_steps
    return out, tuple(changed)


def _text_blob(step: Mapping[str, Any]) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(step)
    return "\n".join(parts)
