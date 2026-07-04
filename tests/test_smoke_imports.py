"""Smoke test: zeus_client public API exports."""
import zeus_client

SYMBOLS = [
    "run_agent", "AgentHooks", "AgentDecision", "load_config", "save_config",
    "load_chat_request", "resolve_contract_for_scope", "list_chat_requests",
    "sync_chat_requests", "SyncResult", "user_chat_requests_dir",
    "compute_contract_hash", "extract_stamped_hash", "client", "logger",
    "BASE_DIR", "MAX_ROUNDS", "normalize_api_version", "to_toon", "resolve_zeus_auth",
    "dispatch_zeus_call", "create_zeus_session", "rehydrate_session", "ZeusClient",
]


def test_public_exports():
    missing = [n for n in SYMBOLS if not hasattr(zeus_client, n)]
    assert not missing, f"Missing exports: {missing}"