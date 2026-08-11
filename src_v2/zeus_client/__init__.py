"""kotenai-zeus-client V2 — journaled hexagonal runtime.

Import as ``zeus_client_v2`` during dual-tree beta. Default ``import zeus_client``
remains the 0.3.1 tree under ``src/`` until default-import cutover (still dual-tree
on this train — see ``docs/V2/MIGRATION.md``).
"""

from __future__ import annotations

from zeus_client_v2._version import __version__
from zeus_client_v2.runtime import ZeusRuntime

# Public surface is imported lazily-friendly: version + runtime first (no cycle
# through zeus_http.headers → package root). Heavier symbols re-exported below.


def __getattr__(name: str):
    # Lazy exports keep ``import zeus_client_v2`` free of adapter cycles.
    _lazy = {
        "VerbResult": ("zeus_client_v2.application.data_verb", "VerbResult"),
        "SuggestHit": ("zeus_client_v2.application.typeahead", "SuggestHit"),
        "SuggestOptions": ("zeus_client_v2.application.typeahead", "SuggestOptions"),
        "SuggestResult": ("zeus_client_v2.application.typeahead", "SuggestResult"),
        "ClientSettings": ("zeus_client_v2.config.models", "ClientSettings"),
        "DataTarget": ("zeus_client_v2.config.models", "DataTarget"),
        "DebugPolicy": ("zeus_client_v2.config.models", "DebugPolicy"),
        "RateLimitPolicy": ("zeus_client_v2.config.models", "RateLimitPolicy"),
        "RuntimeConfig": ("zeus_client_v2.config.models", "RuntimeConfig"),
        "compute_contract_hash": ("zeus_client_v2.domain.contract", "compute_contract_hash"),
        "extract_stamped_hash": ("zeus_client_v2.domain.contract", "extract_stamped_hash"),
        "ErrorCode": ("zeus_client_v2.domain.errors", "ErrorCode"),
        "ZeusClientError": ("zeus_client_v2.domain.errors", "ZeusClientError"),
        "peel_layer_a_summary": ("zeus_client_v2.domain.layer_a", "peel_layer_a_summary"),
        "user_facing_answer": ("zeus_client_v2.domain.layer_a", "user_facing_answer"),
        "DebugBundle": ("zeus_client_v2.domain.messages", "DebugBundle"),
        "TurnRequest": ("zeus_client_v2.domain.messages", "TurnRequest"),
        "TurnResult": ("zeus_client_v2.domain.messages", "TurnResult"),
        "TurnStatus": ("zeus_client_v2.domain.messages", "TurnStatus"),
        "SessionHandle": ("zeus_client_v2.domain.session", "SessionHandle"),
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
]
