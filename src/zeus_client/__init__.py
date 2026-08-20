"""kotenai-zeus-client 2.3 — journaled hexagonal runtime (default import).

``import zeus_client`` loads the ZeusRuntime tree. Temporary alias
``import zeus_client_v2`` re-exports this package with DeprecationWarning
(remove ≤2.2.0). Free-function migration aid: ``zeus_client.compat.v1``.
See ``docs/V2/MIGRATION.md``.
"""

from __future__ import annotations

from typing import Any

from zeus_client._version import __version__
from zeus_client.runtime import ZeusRuntime

# Public surface is imported lazily-friendly: version + runtime first (no cycle
# through zeus_http.headers → package root). Heavier symbols re-exported below.


def __getattr__(name: str) -> Any:
    # Lazy exports keep ``import zeus_client`` free of adapter cycles.
    _lazy = {
        "VerbResult": ("zeus_client.application.data_verb", "VerbResult"),
        "SuggestHit": ("zeus_client.application.typeahead", "SuggestHit"),
        "SuggestOptions": ("zeus_client.application.typeahead", "SuggestOptions"),
        "SuggestResult": ("zeus_client.application.typeahead", "SuggestResult"),
        "ClientSettings": ("zeus_client.config.models", "ClientSettings"),
        "DataTarget": ("zeus_client.config.models", "DataTarget"),
        "DebugPolicy": ("zeus_client.config.models", "DebugPolicy"),
        "RateLimitPolicy": ("zeus_client.config.models", "RateLimitPolicy"),
        "RuntimeConfig": ("zeus_client.config.models", "RuntimeConfig"),
        "compute_contract_hash": ("zeus_client.domain.contract", "compute_contract_hash"),
        "extract_stamped_hash": ("zeus_client.domain.contract", "extract_stamped_hash"),
        "ErrorCode": ("zeus_client.domain.errors", "ErrorCode"),
        "ZeusClientError": ("zeus_client.domain.errors", "ZeusClientError"),
        "peel_layer_a_summary": ("zeus_client.domain.layer_a", "peel_layer_a_summary"),
        "user_facing_answer": ("zeus_client.domain.layer_a", "user_facing_answer"),
        "DebugBundle": ("zeus_client.domain.messages", "DebugBundle"),
        "TurnRequest": ("zeus_client.domain.messages", "TurnRequest"),
        "TurnResult": ("zeus_client.domain.messages", "TurnResult"),
        "TurnStatus": ("zeus_client.domain.messages", "TurnStatus"),
        "SessionHandle": ("zeus_client.domain.session", "SessionHandle"),
        "sum_provider_tokens": ("zeus_client.application.tokens", "sum_provider_tokens"),
        "attach_trace_tokens": ("zeus_client.application.tokens", "attach_trace_tokens"),
        "normalize_usage": ("zeus_client.application.tokens", "normalize_usage"),
        "JobHandle": ("zeus_client.domain.jobs", "JobHandle"),
        "JobEvent": ("zeus_client.domain.jobs", "JobEvent"),
        "JobBudgets": ("zeus_client.domain.jobs", "JobBudgets"),
        "JobSnapshot": ("zeus_client.domain.jobs", "JobSnapshot"),
        "UnitConfig": ("zeus_client.domain.jobs", "UnitConfig"),
        "UnitKind": ("zeus_client.domain.jobs", "UnitKind"),
        "UnitResult": ("zeus_client.domain.jobs", "UnitResult"),
        "UnitStatus": ("zeus_client.domain.jobs", "UnitStatus"),
        "LlmRoleConfig": ("zeus_client.config.models", "LlmRoleConfig"),
        "JobsConfig": ("zeus_client.config.models", "JobsConfig"),
    }
    if name not in _lazy:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_name, attr = _lazy[name]
    import importlib

    mod = importlib.import_module(mod_name)
    val = getattr(mod, attr)
    globals()[name] = val
    return val


__all__ = [
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
]
