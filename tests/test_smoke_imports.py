"""Smoke test: zeus_client 2.0 public API exports (Runtime tree)."""

import zeus_client

SYMBOLS = [
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
]


def test_public_exports():
    missing = [n for n in SYMBOLS if not hasattr(zeus_client, n)]
    assert not missing, f"Missing exports: {missing}"


def test_version_is_2_0_0():
    assert zeus_client.__version__ == "2.1.0"


def test_runtime_importable():
    from zeus_client import ZeusRuntime

    assert ZeusRuntime is not None
    assert "ZeusRuntime" in zeus_client.__all__
