"""Runtime contract audit appended to trace notes after each turn."""


def run_runtime_contract_audit(trace: dict, user_msg: str, stamped_h: str,
                               current_content_h: str, contract_hash: str,
                               contract_id: str) -> None:
    """Append PASS/FAIL audit checks to trace (mirrors E2E tool output)."""
    try:
        audit_checks = []

        def _rec(name, ok, detail=""):
            st = "PASS" if ok else "FAIL"
            audit_checks.append((name, st, detail))
            trace["notes"].append(f"[{st}] {name}" + (f"  ({detail})" if detail else ""))

        has_real = bool(stamped_h) and "TO_BE_FILLED" not in str(stamped_h or "")
        _rec("Source file has real embedded contract (not TO_BE_FILLED)", has_real, stamped_h or "missing")

        emb_match = bool(stamped_h) and stamped_h == current_content_h
        _rec("Embedded hash matches compute on loaded object", emb_match)

        bound_real = bool(contract_hash) and "TO_BE_FILLED" not in str(contract_hash or "")
        _rec("Config binding is real (non-placeholder)", bound_real, contract_hash or "none")

        bound_match_sent = bool(contract_hash) and contract_hash == current_content_h
        _rec("Bound contract_hash matches the payload hash we sent (no drift on send)", bound_match_sent,
             f"bound={contract_hash} payload={current_content_h}")

        cst = (trace.get("session") or {}).get("contract_status") or "none"
        good_status = (cst == "match") or (not contract_id and cst in ("none", "match"))
        _rec("Session created with contract_status=match (or intentionally none)", good_status, f"status={cst}")

        err = str(trace.get("session_error", ""))
        no_drift = "contract_mismatch" not in err and "drift" not in cst.lower()
        _rec("No contract_mismatch / drift error on session create", no_drift)

        no_tracking = "Session tracking failed" not in err
        _rec("No 'Session tracking failed' / contract_mismatch in response", no_tracking)

        passed = sum(1 for _, s, _ in audit_checks if s == "PASS")
        tot = len(audit_checks)
        ovr = "PASS" if (tot > 0 and passed == tot) else "FAIL"

        trace["notes"].append("")
        trace["notes"].append("=== RUNTIME BASIC CHAT AUDIT ===")
        trace["notes"].append(f"Message used: {user_msg}")
        for nm, st, dt in audit_checks:
            trace["notes"].append(f"[{st}] {nm}" + (f"  ({dt})" if dt else ""))
        trace["notes"].append(f"OVERALL RUNTIME: {ovr}  ({passed}/{tot} checks passed)")

        trace["runtime_basic_chat_audit"] = {
            "message": user_msg,
            "checks": [{"name": n, "status": s, "detail": d} for n, s, d in audit_checks],
            "overall": ovr,
            "passed": passed,
            "total": tot,
        }
    except Exception as audit_err:
        trace["notes"].append(f"runtime_audit_failed: {audit_err}")