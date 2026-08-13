"""Smoke test: zeus_client public API exports."""
import zeus_client

SYMBOLS = [
    "run_agent", "AgentHooks", "AgentDecision", "load_config", "save_config",
    "load_chat_request", "resolve_contract_for_scope", "list_chat_requests",
    "sync_chat_requests", "SyncResult", "user_chat_requests_dir",
    "compute_contract_hash", "extract_stamped_hash", "client", "logger",
    "BASE_DIR", "MAX_ROUNDS", "normalize_api_version", "to_toon", "resolve_zeus_auth",
    "dispatch_zeus_call", "create_zeus_session", "rehydrate_session", "ZeusClient",
    "lint_chat_request", "lint_catalog_assembled", "ConflictReport", "Finding",
    "CatalogLintConfig", "hash_policy_summary", "resolve_lint_config",
    "structured_rule_schema", "clear_lint_cache",
    "ClientSettings", "load_base_catalog", "list_base_catalogs", "parse_layer_a",
    "decide_policy", "prepare_settings", "merge_rules", "LayerA", "PolicyDecision",
    "effective_ai_process_result",
    "looks_like_layer_a_dump",
    "user_facing_answer",
    "peel_layer_a_summary",
    "effective_force_trace",
    "run_search", "run_search_from_config",
    "SuggestHit", "SuggestOptions", "SuggestResult", "CouchbaseQueryConfig",
    "run_verb", "run_verb_from_config", "VerbResult", "EXPOSED_V2_VERBS",
    "run_describe", "run_explain", "run_get", "run_find", "run_set",
    "run_order", "run_enrich", "run_project", "run_traverse",
    "run_analyze", "run_return", "run_search_verb",
    "select_primary_req_id", "build_aggregate_trace_payload",
    "sum_provider_tokens", "attach_trace_tokens", "normalize_usage",
]


def test_public_exports():
    missing = [n for n in SYMBOLS if not hasattr(zeus_client, n)]
    assert not missing, f"Missing exports: {missing}"