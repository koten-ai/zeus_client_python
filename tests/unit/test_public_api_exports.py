"""Freeze GA public surface for zeus_client (ZCM-034 / ZCP-37 / ZCP-39)."""

from __future__ import annotations

import zeus_client as zc

# Expected public names from IG Phase 8 / package root __all__
# — never application.* internal modules.
EXPECTED_PUBLIC = frozenset(
    {
        "__version__",
        "ZeusRuntime",
        "RuntimeConfig",
        "ClientSettings",
        "DataTarget",
        "DebugPolicy",
        "RateLimitPolicy",
        "TurnRequest",
        "TurnResult",
        "TurnStatus",
        "DebugBundle",
        "SessionHandle",
        "VerbResult",
        "SuggestResult",
        "SuggestHit",
        "SuggestOptions",
        "ErrorCode",
        "ZeusClientError",
        "compute_contract_hash",
        "extract_stamped_hash",
        "peel_layer_a_summary",
        "user_facing_answer",
        "sum_provider_tokens",
        "attach_trace_tokens",
        "normalize_usage",
        "JobHandle",
        "JobEvent",
        "JobBudgets",
        "JobSnapshot",
        "UnitConfig",
        "UnitKind",
        "UnitResult",
        "UnitStatus",
        "LlmRoleConfig",
        "JobsConfig",
    }
)


def test_public_all_matches_freeze() -> None:
    assert frozenset(zc.__all__) == EXPECTED_PUBLIC


def test_public_symbols_importable() -> None:
    missing = [n for n in EXPECTED_PUBLIC if n != "__version__" and not hasattr(zc, n)]
    assert not missing, f"Missing public exports: {missing}"
    assert zc.__version__ == "2.4.1"
    assert zc.ZeusRuntime is not None


def test_no_application_in_public_all() -> None:
    """Demos must not use application.* — it is internal (not on __all__)."""
    assert "application" not in zc.__all__
    import pytest

    with pytest.raises(AttributeError):
        _ = zc.agent_turn  # type: ignore[attr-defined]
