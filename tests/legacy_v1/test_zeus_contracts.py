"""Tests for python3/zeus/contracts.py — contract binding resolution."""

from zeus_client.zeus.contracts import resolve_contract_for_scope

BUCKET = "beer-sample"
SCOPE = "_default"
KEY = f"{BUCKET}/{SCOPE}"


def test_no_zcfg_returns_empty():
    assert resolve_contract_for_scope(None, BUCKET, SCOPE) == ("", "")
    assert resolve_contract_for_scope({}, BUCKET, SCOPE) == ("", "")


def test_mode_specific_override():
    zcfg = {
        "scope_contracts": {
            KEY: {
                "contract_id": "scope-default",
                "contract_hash": "hash-default",
                "analytics": {
                    "contract_id": "analytics-id",
                    "contract_hash": "analytics-hash",
                },
            },
        },
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE, mode="analytics")
    assert cid == "analytics-id"
    assert ch == "analytics-hash"


def test_mode_specific_empty_falls_through_to_scope_default():
    zcfg = {
        "scope_contracts": {
            KEY: {
                "contract_id": "scope-id",
                "contract_hash": "scope-hash",
                "analytics": {"contract_id": "", "contract_hash": ""},
            },
        },
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE, mode="analytics")
    assert cid == "scope-id"
    assert ch == "scope-hash"


def test_mode_specific_non_dict_ignored():
    zcfg = {
        "scope_contracts": {
            KEY: {
                "contract_id": "scope-id",
                "contract_hash": "scope-hash",
                "analytics": "not-a-dict",
            },
        },
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE, mode="analytics")
    assert cid == "scope-id"
    assert ch == "scope-hash"


def test_scope_default():
    zcfg = {
        "scope_contracts": {
            KEY: {"contract_id": "  cid-scope  ", "contract_hash": " hash-scope "},
        },
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE)
    assert cid == "cid-scope"
    assert ch == "hash-scope"


def test_scope_default_partial_hash_only():
    zcfg = {"scope_contracts": {KEY: {"contract_hash": "only-hash"}}}
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE)
    assert cid == ""
    assert ch == "only-hash"


def test_flat_fallback():
    zcfg = {
        "scope_contracts": {KEY: {"contract_id": "", "contract_hash": ""}},
        "contract_id": "flat-id",
        "contract_hash": "flat-hash",
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE)
    assert cid == "flat-id"
    assert ch == "flat-hash"


def test_flat_fallback_when_scope_missing():
    zcfg = {"contract_id": "flat-only", "contract_hash": "flat-h"}
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE)
    assert cid == "flat-only"
    assert ch == "flat-h"


def test_empty_scope_contracts_entry():
    zcfg = {"scope_contracts": {KEY: {}}}
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE, mode="auto")
    assert cid == ""
    assert ch == ""


def test_non_dict_scope_contract_falls_through_to_flat():
    zcfg = {
        "scope_contracts": {KEY: "not-a-dict"},
        "contract_id": "flat-id",
        "contract_hash": "flat-hash",
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE)
    assert cid == "flat-id"
    assert ch == "flat-hash"


def test_mode_without_match_uses_scope_default():
    zcfg = {
        "scope_contracts": {
            KEY: {
                "contract_id": "scope-id",
                "contract_hash": "scope-hash",
                "other_mode": {"contract_id": "other", "contract_hash": "other-h"},
            },
        },
    }
    cid, ch = resolve_contract_for_scope(zcfg, BUCKET, SCOPE, mode="research")
    assert cid == "scope-id"
    assert ch == "scope-hash"
