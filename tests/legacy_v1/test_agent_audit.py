"""Tests for python3/agent/audit.py — runtime contract audit."""
import pytest

from zeus_client.agent.audit import run_runtime_contract_audit


def _trace(session_status="match", session_error=""):
    return {
        "notes": [],
        "session": {"contract_status": session_status},
        "session_error": session_error,
    }


def test_audit_all_pass():
    trace = _trace("match")
    run_runtime_contract_audit(
        trace, "hello", "md5:real-stamped", "md5:real-stamped",
        "md5:real-stamped", "contract-1",
    )
    assert trace["runtime_basic_chat_audit"]["overall"] == "PASS"
    assert trace["runtime_basic_chat_audit"]["passed"] == 7
    assert any("OVERALL RUNTIME: PASS" in n for n in trace["notes"])


def test_audit_fails_placeholder_stamped():
    trace = _trace("match")
    run_runtime_contract_audit(
        trace, "hi", "TO_BE_FILLED", "md5:computed",
        "md5:bound", "cid",
    )
    audit = trace["runtime_basic_chat_audit"]
    assert audit["overall"] == "FAIL"
    names = {c["name"]: c["status"] for c in audit["checks"]}
    assert names["Source file has real embedded contract (not TO_BE_FILLED)"] == "FAIL"
    assert names["Embedded hash matches compute on loaded object"] == "FAIL"


def test_audit_fails_bound_placeholder():
    trace = _trace("none")
    run_runtime_contract_audit(trace, "q", "md5:a", "md5:a", "TO_BE_FILLED", "")
    names = {c["name"]: c["status"] for c in trace["runtime_basic_chat_audit"]["checks"]}
    assert names["Config binding is real (non-placeholder)"] == "FAIL"


def test_audit_bound_hash_drift():
    trace = _trace("match")
    run_runtime_contract_audit(trace, "q", "md5:a", "md5:b", "md5:c", "cid")
    names = {c["name"]: c["status"] for c in trace["runtime_basic_chat_audit"]["checks"]}
    assert names["Bound contract_hash matches the payload hash we sent (no drift on send)"] == "FAIL"


def test_audit_contract_status_drift():
    trace = _trace("drift")
    run_runtime_contract_audit(trace, "q", "md5:a", "md5:a", "md5:a", "cid")
    names = {c["name"]: c["status"] for c in trace["runtime_basic_chat_audit"]["checks"]}
    assert names["Session created with contract_status=match (or intentionally none)"] == "FAIL"
    assert names["No contract_mismatch / drift error on session create"] == "FAIL"


def test_audit_intentional_none_without_contract_id():
    trace = _trace("none")
    run_runtime_contract_audit(trace, "q", "", "", "", "")
    names = {c["name"]: c["status"] for c in trace["runtime_basic_chat_audit"]["checks"]}
    assert names["Session created with contract_status=match (or intentionally none)"] == "PASS"


def test_audit_session_tracking_failed():
    trace = _trace("match", session_error="Session tracking failed: contract_mismatch")
    run_runtime_contract_audit(trace, "q", "md5:a", "md5:a", "md5:a", "cid")
    names = {c["name"]: c["status"] for c in trace["runtime_basic_chat_audit"]["checks"]}
    assert names["No contract_mismatch / drift error on session create"] == "FAIL"
    assert names["No 'Session tracking failed' / contract_mismatch in response"] == "FAIL"


def test_audit_exception_is_captured(monkeypatch):
    trace = _trace()
    original = sum

    def bad_sum(iterable, start=0):
        if hasattr(iterable, "__iter__") and not isinstance(iterable, (str, bytes)):
            raise RuntimeError("sum failed")
        return original(iterable, start)

    monkeypatch.setattr("builtins.sum", bad_sum)
    run_runtime_contract_audit(trace, "q", "md5:a", "md5:a", "md5:a", "cid")
    assert any("runtime_audit_failed" in str(n) for n in trace["notes"])