"""Zeus Python client library."""

from zeus_client.agent.hooks import AgentDecision, AgentHooks
from zeus_client.agent.layer_a import LayerA, parse_layer_a, normalize_triggers
from zeus_client.agent.loop import run_agent
from zeus_client.agent.policy import PolicyDecision, decide_policy
from zeus_client.agent.response import StructuredAgentResponse, extract_structured_response
from zeus_client.agent.settings import ClientSettings, freeze_session_rules, merge_rules, prepare_settings, effective_ai_process_result
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
from zeus_client.zeus.session import (
    continue_session_turn,
    create_zeus_session,
    post_session_trace,
    rehydrate_session,
)
from zeus_client.trace.tool_order import build_tool_order


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
    "PolicyDecision",
    "StructuredAgentResponse",
    "decide_policy",
    "effective_ai_process_result",
    "extract_structured_response",
    "freeze_session_rules",
    "list_base_catalogs",
    "load_base_catalog",
    "merge_rules",
    "normalize_triggers",
    "parse_layer_a",
    "prepare_settings",
    "BASE_DIR",
    "build_tool_order",
    "MAX_ROUNDS",
    "USER_CONFIG_DIR",
    "ZeusClient",
    "__version__",
    "client",
    "close_http",
    "compute_contract_hash",
    "continue_session_turn",
    "create_zeus_session",
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
    "save_config",
    "sync_chat_requests",
    "SyncResult",
    "to_toon",
    "user_chat_requests_dir",
    "user_config_dir",
    "zeus_correlation_headers",
]
