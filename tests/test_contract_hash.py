"""Contract hash unit tests."""
import zeus_client.contract_hash as ch
from zeus_client.contract_hash import (
    compute_contract_hash,
    extract_stamped_hash,
    resolve_session_contract_hash,
    _canonicalize,
    _strip_for_hash,
    _strip_scope_brief,
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