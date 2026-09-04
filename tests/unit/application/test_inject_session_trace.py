"""Hub-shaped session-trace inject bag (ZCP-114)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from zeus_client.application.detective.extract import (
    inject_for_session_trace,
    parse_mini_entity_types,
    sha12,
    slice_block,
)

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "system_with_brief_mini.txt"


def _independent_slice(text: str, heading: str) -> str:
    """Oracle slice: heading until next H2 (not this heading), then strip."""
    idx = text.find(heading)
    if idx < 0:
        return ""
    kept: list[str] = []
    for i, ln in enumerate(text[idx:].splitlines()):
        if i > 0 and ln.startswith("## ") and not ln.startswith(heading):
            break
        kept.append(ln)
    return "\n".join(kept).strip()


def test_inject_for_session_trace_hub_shape_golden() -> None:
    sys = _FIXTURE.read_text(encoding="utf-8")
    bag = inject_for_session_trace(system=sys, catalog={})
    mini = _independent_slice(sys, "## MINI-SCHEMA")
    brief = _independent_slice(sys, "## SCOPE BRIEF")
    expected_sha12 = hashlib.sha256(mini.encode("utf-8")).hexdigest()[:12]
    expected_brief = hashlib.sha256(brief.encode("utf-8")).hexdigest()[:12]

    assert bag["source"] == "client_llm"
    assert bag["mini_schema"]["present"] is True
    assert bag["mini_schema"]["sha12"] == expected_sha12
    assert bag["mini_schema"]["sha12"] == sha12(slice_block(sys, "mini"))
    assert "hotel" in bag["mini_schema"]["entity_types"]
    assert bag["mini_schema"]["entity_types"] == [
        "Activity",
        "Airline",
        "Airport",
        "hotel",
        "route",
    ]
    assert bag["system_chars"] == len(sys.encode("utf-8"))
    assert bag["scope_brief"]["present"] is True
    assert bag["scope_brief"]["sha12"] == expected_brief
    assert bag["scope_brief"]["scope_line"] == "travel-sample/inventory"
    assert bag["scope_brief"]["mode_line"] == "analytics"
    assert bag["scope_brief"]["chars"] == len(brief.encode("utf-8"))
    assert bag["mini_schema"]["chars"] == len(mini.encode("utf-8"))
    assert bag["scope_brief"]["preview"].startswith("## SCOPE BRIEF")
    assert bag["mini_schema"]["preview"].startswith("## MINI-SCHEMA")
    assert "text" not in bag["scope_brief"]
    assert "text" not in bag["mini_schema"]
    assert bag["mini_schema"]["sha12"] != hashlib.sha256(sys.encode("utf-8")).hexdigest()[:12]


def test_inject_entity_types_from_mini_text_not_catalog() -> None:
    sys = _FIXTURE.read_text(encoding="utf-8")
    bag = inject_for_session_trace(
        system=sys,
        catalog={"mini_entity_types": ["Nope"], "has_mini_schema": True},
    )
    assert "Nope" not in bag["mini_schema"]["entity_types"]
    assert parse_mini_entity_types(slice_block(sys, "mini")) == bag["mini_schema"]["entity_types"]


def test_inject_absent_sections() -> None:
    bag = inject_for_session_trace(system="You are helpful. No markers.")
    assert bag["scope_brief"] == {"present": False, "chars": 0}
    assert bag["mini_schema"] == {"present": False, "chars": 0}
    assert "sha12" not in bag["scope_brief"]
    assert "sha12" not in bag["mini_schema"]
    assert bag["system_chars"] == len(b"You are helpful. No markers.")


def test_inject_rewind_includes_capped_text() -> None:
    sys = _FIXTURE.read_text(encoding="utf-8")
    slim = inject_for_session_trace(system=sys, rewind=False)
    fat = inject_for_session_trace(system=sys, rewind=True)
    assert "text" not in slim["mini_schema"]
    assert "text" not in slim["scope_brief"]
    assert fat["mini_schema"]["text"].startswith("## MINI-SCHEMA")
    assert fat["scope_brief"]["text"].startswith("## SCOPE BRIEF")
    assert "truncated" not in fat["mini_schema"]
    assert fat["mini_schema"]["sha12"] == slim["mini_schema"]["sha12"]


def test_inject_rewind_caps_text_at_96_kib(monkeypatch) -> None:
    from zeus_client.application.detective import extract as extract_mod

    sys = _FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(extract_mod, "INJECT_SECTION_MAX_BYTES", 32)
    bag = extract_mod.inject_for_session_trace(system=sys, rewind=True)
    assert bag["mini_schema"]["truncated"] is True
    assert bag["mini_schema"]["text"].endswith("…[truncated]")
    # 32-byte cap + truncation marker, not the full mini slice.
    assert len(bag["mini_schema"]["text"].encode("utf-8")) < len(
        slice_block(sys, "mini").encode("utf-8")
    )
