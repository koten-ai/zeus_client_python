"""Zeus Python client library."""

from zeus_client.agent.hooks import AgentDecision, AgentHooks
from zeus_client.agent.layer_a import LayerA, parse_layer_a, normalize_triggers, peel_layer_a_summary, user_facing_answer, looks_like_layer_a_dump
from zeus_client.agent.loop import run_agent
from zeus_client.agent.policy import PolicyDecision, decide_policy
from zeus_client.agent.response import StructuredAgentResponse, extract_structured_response, layer_a_for_session_trace
from zeus_client.agent.settings import ClientSettings, freeze_session_rules, merge_rules, prepare_settings, effective_ai_process_result, effective_force_trace
from zeus_client.config import (
    load_config,
    resolve_llm_provider_config,
    resolve_zeus_config,
    save_config,
)
from zeus_client.constants import (
    BASE_DIR,
    MAX_ROUNDS,
    USER_CONFIG_DIR,
    __version__,
    normalize_api_version,
    user_chat_requests_dir,
    user_config_dir,
)
from zeus_client.contract_hash import (
    compute_contract_hash,
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
)
from zeus_client.http_client import client, close_http, init_http
from zeus_client.logging_setup import logger
from zeus_client.toon import to_toon
from zeus_client.zeus.auth import invalidate_zeus_session, resolve_zeus_auth
from zeus_client.zeus.base_catalog import list_base_catalogs, load_base_catalog
from zeus_client.zeus.catalog import list_chat_requests, load_chat_request
from zeus_client.zeus.lint import (
    CatalogLintConfig,
    ConflictReport,
    Finding,
    clear_lint_cache,
    hash_policy_summary,
    lint_catalog_assembled,
    lint_chat_request,
    resolve_lint_config,
    structured_rule_schema,
)
from zeus_client.zeus.sync import SyncResult, sync_chat_requests
from zeus_client.zeus.contracts import resolve_contract_for_scope
from zeus_client.zeus.dispatch import (
    dispatch_zeus_call,
    dispatch_zeus_tool,
    dispatch_zeus_v2_verb,
    zeus_correlation_headers,
)
from zeus_client.zeus.suggest import (
    CouchbaseQueryConfig,
    SuggestHit,
    SuggestOptions,
    SuggestResult,
    run_search,
    run_search_from_config,
)
from zeus_client.zeus.verbs import (
    EXPOSED_V2_VERBS,
    VerbResult,
    run_analyze,
    run_describe,
    run_enrich,
    run_explain,
    run_find,
    run_get,
    run_order,
    run_project,
    run_return,
    run_search_verb,
    run_set,
    run_traverse,
    run_verb,
    run_verb_from_config,
)
from zeus_client.zeus.session import (
    continue_session_turn,
    create_zeus_session,
    post_session_trace,
    rehydrate_session,
)
from zeus_client.trace.tool_order import build_tool_order
from zeus_client.trace.session_hops import (
    select_primary_req_id,
    build_aggregate_trace_payload,
)
from zeus_client.trace.tokens import (
    attach_trace_tokens,
    normalize_usage,
    sum_provider_tokens,
)


class ZeusClient:
    """Async context manager wrapping HTTP client lifecycle."""

    async def __aenter__(self):
        await init_http()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await close_http()
        return False


__all__ = [
    "AgentDecision",
    "AgentHooks",
    "ClientSettings",
    "LayerA",
    "looks_like_layer_a_dump",
    "peel_layer_a_summary",
    "user_facing_answer",
    "PolicyDecision",
    "StructuredAgentResponse",
    "decide_policy",
    "effective_ai_process_result",
    "effective_force_trace",
    "extract_structured_response",
    "layer_a_for_session_trace",
    "freeze_session_rules",
    "list_base_catalogs",
    "load_base_catalog",
    "merge_rules",
    "normalize_triggers",
    "parse_layer_a",
    "prepare_settings",
    "BASE_DIR",
    "build_aggregate_trace_payload",
    "build_tool_order",
    "select_primary_req_id",
    "sum_provider_tokens",
    "attach_trace_tokens",
    "normalize_usage",
    "MAX_ROUNDS",
    "USER_CONFIG_DIR",
    "ZeusClient",
    "__version__",
    "client",
    "close_http",
    "compute_contract_hash",
    "continue_session_turn",
    "create_zeus_session",
    "CouchbaseQueryConfig",
    "dispatch_zeus_call",
    "dispatch_zeus_tool",
    "dispatch_zeus_v2_verb",
    "extract_stamped_hash",
    "heal_trailing_ws_stamp_drift",
    "init_http",
    "invalidate_zeus_session",
    "list_chat_requests",
    "load_chat_request",
    "load_config",
    "logger",
    "CatalogLintConfig",
    "ConflictReport",
    "Finding",
    "clear_lint_cache",
    "hash_policy_summary",
    "lint_catalog_assembled",
    "lint_chat_request",
    "resolve_lint_config",
    "structured_rule_schema",
    "normalize_api_version",
    "post_session_trace",
    "rehydrate_session",
    "resolve_contract_for_scope",
    "resolve_llm_provider_config",
    "resolve_zeus_auth",
    "resolve_zeus_config",
    "run_agent",
    "run_verb",
    "run_verb_from_config",
    "run_describe",
    "run_explain",
    "run_get",
    "run_find",
    "run_set",
    "run_order",
    "run_enrich",
    "run_project",
    "run_traverse",
    "run_analyze",
    "run_return",
    "run_search_verb",
    "run_search",
    "run_search_from_config",
    "save_config",
    "SuggestHit",
    "SuggestOptions",
    "SuggestResult",
    "EXPOSED_V2_VERBS",
    "VerbResult",
    "sync_chat_requests",
    "SyncResult",
    "to_toon",
    "user_chat_requests_dir",
    "user_config_dir",
    "zeus_correlation_headers",
]
