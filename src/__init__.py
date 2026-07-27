"""Zeus Python client library."""

from zeus_client.agent.control_plane import (
    DEFAULT_JAILBREAK_RULES,
    OutputRequestError,
    PolicyResult,
    RuleMergeError,
    SettingsBag,
    apply_policy_table,
    apply_policy_table_from_payload,
    freeze_rules,
    inject_control_plane_blocks,
    merge_rules,
    normalize_output_request_app_fields,
    render_company_context_block,
    render_output_request_block,
    render_rules_block,
    ruleset_id,
    settings_from_mapping,
    truncate_company_context,
    validate_app_output,
)
from zeus_client.agent.hooks import AgentDecision, AgentHooks
from zeus_client.agent.layer_a import LayerABag, parse_layer_a, parse_layer_a_from_trace
from zeus_client.agent.loop import run_agent
from zeus_client.agent.response import StructuredAgentResponse, extract_structured_response
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
from zeus_client.contract_hash import compute_contract_hash, extract_stamped_hash
from zeus_client.http_client import client, close_http, init_http
from zeus_client.logging_setup import logger
from zeus_client.toon import to_toon
from zeus_client.zeus.auth import invalidate_zeus_session, resolve_zeus_auth
from zeus_client.zeus.catalog import (
    list_chat_requests,
    load_chat_request,
    load_chat_request_file,
    chat_request_path,
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
    "DEFAULT_JAILBREAK_RULES",
    "LayerABag",
    "OutputRequestError",
    "PolicyResult",
    "RuleMergeError",
    "SettingsBag",
    "StructuredAgentResponse",
    "apply_policy_table",
    "apply_policy_table_from_payload",
    "BASE_DIR",
    "build_tool_order",
    "chat_request_path",
    "extract_structured_response",
    "freeze_rules",
    "inject_control_plane_blocks",
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
    "init_http",
    "invalidate_zeus_session",
    "list_chat_requests",
    "load_chat_request",
    "load_chat_request_file",
    "load_config",
    "logger",
    "merge_rules",
    "normalize_api_version",
    "normalize_output_request_app_fields",
    "parse_layer_a",
    "parse_layer_a_from_trace",
    "post_session_trace",
    "rehydrate_session",
    "render_company_context_block",
    "render_output_request_block",
    "render_rules_block",
    "resolve_contract_for_scope",
    "resolve_llm_provider_config",
    "resolve_zeus_auth",
    "resolve_zeus_config",
    "ruleset_id",
    "run_agent",
    "save_config",
    "settings_from_mapping",
    "sync_chat_requests",
    "SyncResult",
    "to_toon",
    "truncate_company_context",
    "user_chat_requests_dir",
    "user_config_dir",
    "validate_app_output",
    "zeus_correlation_headers",
]