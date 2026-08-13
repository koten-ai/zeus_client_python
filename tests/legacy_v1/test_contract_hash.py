"""Contract hash unit tests."""

import zeus_client.contract_hash as ch
from zeus_client.contract_hash import (
    _canonicalize,
    _strip_for_hash,
    _strip_scope_brief,
    compute_contract_hash,
    extract_stamped_hash,
    resolve_session_contract_hash,
)


def test_strip_scope_brief():
    content = "rules" + ch.SCOPE_BRIEF_MARKER + "\n## MINI-SCHEMA\nstuff"
    assert _strip_scope_brief(content) == "rules"
    assert _strip_scope_brief(123) == ""
    assert _strip_scope_brief("no marker") == "no marker"


def test_strip_for_hash_excludes_metadata():
    obj = {
        "_hidden": 1,
        "guidance": {"x": 1},
        "contract": {"hash": "md5:abc"},
        "metadata": {"at": 1},
        "model": "gpt",
        "messages": [{"role": "system", "content": "x" + ch.SCOPE_BRIEF_MARKER + " brief"}],
    }
    out = _strip_for_hash(obj)
    assert "_hidden" not in out
    assert "guidance" not in out
    assert "contract" not in out
    assert "model" not in out
    assert out["messages"][0]["content"] == "x"


def test_canonicalize_sorts_keys():
    assert _canonicalize({"b": 1, "a": 2}) == {"a": 2, "b": 1}


def test_compute_contract_hash_non_dict():
    assert compute_contract_hash([]) == ""


def test_compute_contract_hash_html_escape():
    doc = {"messages": [{"role": "system", "content": "a & b < c > d"}]}
    h = compute_contract_hash(doc)
    assert h.startswith("md5:")


def test_resolve_session_contract_hash_prefers_payload_on_drift():
    h, src = resolve_session_contract_hash("md5:bound", "md5:stamped", "md5:payload")
    assert h == "md5:payload"
    assert src == "payload_hash"


def test_resolve_session_contract_hash_stamped_match():
    h, src = resolve_session_contract_hash("md5:bound", "md5:same", "md5:same")
    assert h == "md5:same"
    assert src == "stamped_matches_payload"


def test_trailing_newline_plus_scope_brief_merge_stable():
    """Live brief merge + strip must not change hash when base prompt has no trailing ws.

    Regression: a trailing ``\\n`` on messages[0].content was kept in the stamp
    (no brief) but removed by strip-for-hash after merge_scope_brief (brief
    present), producing 409 contract_mismatch on /v2/session.
    """
    from copy import deepcopy

    from zeus_client.zeus.catalog import merge_scope_brief

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

    merged = merge_scope_brief(base, "## SCOPE BRIEF\nscope: demo/_default\nmode: analytics")
    assert compute_contract_hash(merged) == h0
    assert "## SCOPE BRIEF" in merged["messages"][0]["content"]


def test_heal_trailing_ws_stamp_drift_rewrites_stamp_and_stabilizes_merge():
    """Stamp of rules text with trailing newline must match post-brief-merge hash after heal."""
    from copy import deepcopy

    from zeus_client.contract_hash import heal_trailing_ws_stamp_drift
    from zeus_client.zeus.catalog import merge_scope_brief

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
    merged_dirty = merge_scope_brief(deepcopy(dirty), "## SCOPE BRIEF\nscope: demo/_default")
    assert compute_contract_hash(merged_dirty) == h_clean
    assert extract_stamped_hash(merged_dirty) == h_dirty
    assert extract_stamped_hash(merged_dirty) != compute_contract_hash(merged_dirty)

    healed = heal_trailing_ws_stamp_drift(dirty)
    assert extract_stamped_hash(healed) == h_clean
    assert compute_contract_hash(healed) == h_clean
    assert healed["messages"][0]["content"] == "rules only"
    assert healed.get("_hash") == h_clean

    merged = merge_scope_brief(healed, "## SCOPE BRIEF\nscope: demo/_default")
    assert extract_stamped_hash(merged) == compute_contract_hash(merged) == h_clean


def test_heal_trailing_ws_stamp_drift_skips_unrelated_stamp_mismatch():
    from zeus_client.contract_hash import heal_trailing_ws_stamp_drift

    doc = {
        "messages": [{"role": "system", "content": "rules only\n"}],
        "contract": {"hash": "md5:not-the-real-compute"},
    }
    out = heal_trailing_ws_stamp_drift(doc)
    assert out is doc
    assert extract_stamped_hash(out) == "md5:not-the-real-compute"


def test_extract_stamped_hash_priority():
    doc = {
        "contract": {"hash": "md5:TO_BE_FILLED"},
        "_hash": "md5:realhash",
        "stamped_chat_request": {"contract": {"hash": "md5:fromwrapper"}},
    }
    assert extract_stamped_hash(doc) == "md5:realhash"
    assert extract_stamped_hash({"contract": {"hash": "md5:direct"}}) == "md5:direct"
    assert extract_stamped_hash("not dict") == ""
    assert extract_stamped_hash({}) == ""


def test_strip_for_hash_passthrough_scalar():
    assert _strip_for_hash(42) == 42


def test_extract_stamped_hash_skips_non_dict_contract_block():
    doc = {
        "contract": "not-a-dict",
        "_hash": "md5:top-level",
    }
    assert extract_stamped_hash(doc) == "md5:top-level"


def test_extract_stamped_hash_second_loop_skips_non_dict_candidate():
    doc = {
        "contract": {"hash": "md5:TO_BE_FILLED"},
        "stamped_chat_request": "bad",
        "stamped": {"_hash": "md5:from-stamped-key"},
    }
    assert extract_stamped_hash(doc) == "md5:from-stamped-key"


def test_extract_stamped_hash_second_pass_skips_placeholder_hash():
    doc = {
        "stamped_chat_request": {"_hash": "md5:TO_BE_FILLED"},
        "stamped": {"hash": "md5:real-from-stamped"},
    }
    assert extract_stamped_hash(doc) == "md5:real-from-stamped"


def test_extract_stamped_hash_second_pass_hash_from_wrapper():
    doc = {
        "contract": {"hash": "md5:TO_BE_FILLED"},
        "stamped_chat_request": {"_hash": "md5:wrapper-only"},
    }
    assert extract_stamped_hash(doc) == "md5:wrapper-only"


def test_extract_stamped_hash_skips_non_dict_wrappers():
    doc = {
        "_hash": "md5:top",
        "stamped_chat_request": "not-a-dict",
        "stamped": ["also-not"],
    }
    assert extract_stamped_hash(doc) == "md5:top"
