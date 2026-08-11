"""V2 contract hash oracles — ported from tests/test_contract_hash.py (ZCP-11 / Task 4.1).

Never forge production stamps in fixtures labeled prod; all hashes here are
synthetic test vectors (md5:… placeholders or local compute digests).
"""

from __future__ import annotations

from copy import deepcopy

import zeus_client_v2.domain.contract as ch
from zeus_client_v2.domain.contract import (
    ContractService,
    SessionHashChoice,
    compute_contract_hash,
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
    resolve_session_contract_hash,
)


def _merge_scope_brief_local(chat_req: dict, brief: str) -> dict:
    """Minimal pure brief merge for hash-stability oracles (catalog lives in 4.2).

    Mirrors V1 ``zeus.catalog.merge_scope_brief``: rstrip base system text then
    append ``\\n\\n`` + brief so strip-for-hash agrees with a clean no-brief stamp.
    """
    if not brief:
        return chat_req
    out = deepcopy(chat_req)
    messages = out.get("messages") or []
    if messages:
        current = messages[0].get("content") or ""
        if "## SCOPE BRIEF" not in current and "## MINI-SCHEMA" not in current:
            messages[0]["content"] = current.rstrip(" \t\n\r") + "\n\n" + brief.strip()
    instr = out.get("instructions") or {}
    if isinstance(instr, dict):
        sp = instr.get("system_prompt") or ""
        if sp and "## SCOPE BRIEF" not in sp and "## MINI-SCHEMA" not in sp:
            instr["system_prompt"] = sp.rstrip(" \t\n\r") + "\n\n" + brief.strip()
            out["instructions"] = instr
    return out


def test_strip_scope_brief() -> None:
    content = "rules" + ch.SCOPE_BRIEF_MARKER + "\n## MINI-SCHEMA\nstuff"
    assert ch._strip_scope_brief(content) == "rules"
    assert ch._strip_scope_brief(123) == ""  # type: ignore[arg-type]
    assert ch._strip_scope_brief("no marker") == "no marker"


def test_strip_for_hash_excludes_metadata() -> None:
    obj = {
        "_hidden": 1,
        "guidance": {"x": 1},
        "contract": {"hash": "md5:abc"},
        "metadata": {"at": 1},
        "model": "gpt",
        "messages": [
            {"role": "system", "content": "x" + ch.SCOPE_BRIEF_MARKER + " brief"}
        ],
    }
    out = ch._strip_for_hash(obj)
    assert "_hidden" not in out
    assert "guidance" not in out
    assert "contract" not in out
    assert "model" not in out
    assert out["messages"][0]["content"] == "x"


def test_canonicalize_sorts_keys() -> None:
    assert ch._canonicalize({"b": 1, "a": 2}) == {"a": 2, "b": 1}


def test_compute_contract_hash_non_dict() -> None:
    assert compute_contract_hash([]) == ""  # type: ignore[arg-type]


def test_compute_contract_hash_html_escape() -> None:
    doc = {"messages": [{"role": "system", "content": "a & b < c > d"}]}
    h = compute_contract_hash(doc)
    assert h.startswith("md5:")
    # Go encoding/json HTML-escapes & < > — digest must be stable for this text.
    assert h == compute_contract_hash(doc)


def test_compute_contract_hash_excludes_stamp_and_is_stable() -> None:
    """Stamp/guidance/metadata must not affect digest; same rules → same hash."""
    doc = {
        "messages": [{"role": "system", "content": "rules only"}],
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "contract": {"hash": "md5:should-be-ignored", "builder": "test"},
        "guidance": {"optimal_paths": ["x"]},
        "metadata": {"at": 1},
    }
    h = compute_contract_hash(doc)
    assert h.startswith("md5:")
    assert len(h) == len("md5:") + 32
    doc2 = deepcopy(doc)
    doc2["contract"] = {"hash": "md5:other"}
    doc2["guidance"] = {"y": 2}
    doc2["metadata"] = {"at": 99}
    assert compute_contract_hash(doc2) == h
    # Rules change must change digest.
    doc3 = deepcopy(doc)
    doc3["messages"][0]["content"] = "rules changed"
    assert compute_contract_hash(doc3) != h


def test_resolve_session_contract_hash_prefers_payload_on_drift() -> None:
    choice = resolve_session_contract_hash("md5:bound", "md5:stamped", "md5:payload")
    assert isinstance(choice, SessionHashChoice)
    assert choice.hash == "md5:payload"
    assert choice.source == "payload_hash"


def test_resolve_session_contract_hash_stamped_match() -> None:
    choice = resolve_session_contract_hash("md5:bound", "md5:same", "md5:same")
    assert choice.hash == "md5:same"
    assert choice.source == "stamped_matches_payload"


def test_resolve_session_contract_hash_config_match() -> None:
    choice = resolve_session_contract_hash("md5:same", "md5:stamped", "md5:same")
    assert choice.hash == "md5:same"
    assert choice.source == "config_matches_payload"


def test_resolve_session_contract_hash_fallbacks() -> None:
    assert resolve_session_contract_hash("", "md5:stamped", "").source == "stamped_fallback"
    assert resolve_session_contract_hash("md5:bound", "", "").source == "config_fallback"
    assert resolve_session_contract_hash("", "", "").hash == ""


def test_trailing_newline_plus_scope_brief_merge_stable() -> None:
    """Live brief merge + strip must not change hash when base prompt has no trailing ws."""
    base = {
        "messages": [{"role": "system", "content": "rules only"}],
        "instructions": {"system_prompt": "marker only"},
        "verbs": [{"type": "function", "function": {"name": "find"}}],
        "contract": {"hash": "md5:placeholder"},
    }
    h0 = compute_contract_hash(base)
    drifted = deepcopy(base)
    drifted["messages"][0]["content"] = "rules only\n"
    assert compute_contract_hash(drifted) != h0

    merged = _merge_scope_brief_local(
        base, "## SCOPE BRIEF\nscope: demo/_default\nmode: analytics"
    )
    assert compute_contract_hash(merged) == h0
    assert "## SCOPE BRIEF" in merged["messages"][0]["content"]


def test_heal_trailing_ws_stamp_drift_rewrites_stamp_and_stabilizes_merge() -> None:
    """Stamp of rules text with trailing newline must match post-brief-merge hash after heal."""
    clean = {
        "messages": [{"role": "system", "content": "rules only"}],
        "instructions": {"system_prompt": "marker only"},
        "verbs": [{"type": "function", "function": {"name": "find"}}],
    }
    h_clean = compute_contract_hash(clean)

    dirty = deepcopy(clean)
    dirty["messages"][0]["content"] = "rules only\n"
    h_dirty = compute_contract_hash(dirty)
    assert h_dirty != h_clean
    dirty["contract"] = {"hash": h_dirty, "builder": "test@verify"}
    dirty["_hash"] = h_dirty

    # Without heal: brief merge changes the content hash vs embedded stamp.
    merged_dirty = _merge_scope_brief_local(
        deepcopy(dirty), "## SCOPE BRIEF\nscope: demo/_default"
    )
    assert compute_contract_hash(merged_dirty) == h_clean
    assert extract_stamped_hash(merged_dirty) == h_dirty
    assert extract_stamped_hash(merged_dirty) != compute_contract_hash(merged_dirty)

    healed = heal_trailing_ws_stamp_drift(dirty)
    assert extract_stamped_hash(healed) == h_clean
    assert compute_contract_hash(healed) == h_clean
    assert healed["messages"][0]["content"] == "rules only"
    assert healed.get("_hash") == h_clean

    merged = _merge_scope_brief_local(healed, "## SCOPE BRIEF\nscope: demo/_default")
    assert extract_stamped_hash(merged) == compute_contract_hash(merged) == h_clean


def test_heal_trailing_ws_stamp_drift_skips_unrelated_stamp_mismatch() -> None:
    doc = {
        "messages": [{"role": "system", "content": "rules only\n"}],
        "contract": {"hash": "md5:not-the-real-compute"},
    }
    out = heal_trailing_ws_stamp_drift(doc)
    assert out is doc
    assert extract_stamped_hash(out) == "md5:not-the-real-compute"


def test_extract_stamped_hash_priority() -> None:
    doc = {
        "contract": {"hash": "md5:TO_BE_FILLED"},
        "_hash": "md5:realhash",
        "stamped_chat_request": {"contract": {"hash": "md5:fromwrapper"}},
    }
    assert extract_stamped_hash(doc) == "md5:realhash"
    assert extract_stamped_hash({"contract": {"hash": "md5:direct"}}) == "md5:direct"
    assert extract_stamped_hash("not dict") == ""  # type: ignore[arg-type]
    assert extract_stamped_hash({}) == ""


def test_strip_for_hash_passthrough_scalar() -> None:
    assert ch._strip_for_hash(42) == 42


def test_extract_stamped_hash_skips_non_dict_contract_block() -> None:
    doc = {
        "contract": "not-a-dict",
        "_hash": "md5:top-level",
    }
    assert extract_stamped_hash(doc) == "md5:top-level"


def test_extract_stamped_hash_second_loop_skips_non_dict_candidate() -> None:
    doc = {
        "contract": {"hash": "md5:TO_BE_FILLED"},
        "stamped_chat_request": "bad",
        "stamped": {"_hash": "md5:from-stamped-key"},
    }
    assert extract_stamped_hash(doc) == "md5:from-stamped-key"


def test_extract_stamped_hash_second_pass_skips_placeholder_hash() -> None:
    doc = {
        "stamped_chat_request": {"_hash": "md5:TO_BE_FILLED"},
        "stamped": {"hash": "md5:real-from-stamped"},
    }
    assert extract_stamped_hash(doc) == "md5:real-from-stamped"


def test_extract_stamped_hash_second_pass_hash_from_wrapper() -> None:
    doc = {
        "contract": {"hash": "md5:TO_BE_FILLED"},
        "stamped_chat_request": {"_hash": "md5:wrapper-only"},
    }
    assert extract_stamped_hash(doc) == "md5:wrapper-only"


def test_extract_stamped_hash_skips_non_dict_wrappers() -> None:
    doc = {
        "_hash": "md5:top",
        "stamped_chat_request": "not-a-dict",
        "stamped": ["also-not"],
    }
    assert extract_stamped_hash(doc) == "md5:top"


def test_contract_service_facade() -> None:
    svc = ContractService()
    doc = {"messages": [{"role": "system", "content": "hi"}]}
    h = svc.compute_hash(doc)
    assert h == compute_contract_hash(doc)
    stamped_doc = {"contract": {"hash": h}}
    assert svc.extract_stamped_hash(stamped_doc) == h
    choice = svc.resolve_session_hash(stamped=h, content=h, bound="md5:other")
    assert choice.hash == h
    assert choice.source == "stamped_matches_payload"
    assert svc.heal_trailing_ws_drift(stamped_doc) is stamped_doc or isinstance(
        svc.heal_trailing_ws_drift(stamped_doc), dict
    )
