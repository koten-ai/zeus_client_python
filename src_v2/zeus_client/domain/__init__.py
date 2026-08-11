"""Domain package — pure types, no httpx/provider SDKs."""

from __future__ import annotations

from zeus_client_v2.domain.catalog import (
    LoadedCatalog,
    chat_request_filename,
    merge_scope_brief,
    resolve_catalog_path,
    scope_chat_requests_subdir,
)
from zeus_client_v2.domain.contract import (
    ContractService,
    SessionHashChoice,
    compute_contract_hash,
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
    resolve_session_contract_hash,
)
from zeus_client_v2.domain.errors import CatalogError, ErrorCode, ZeusClientError
from zeus_client_v2.domain.ids import CallId, ChatId, ReqId, SessionId, TurnId
from zeus_client_v2.domain.session import SessionHandle

__all__ = [
    "TurnId",
    "ChatId",
    "CallId",
    "SessionId",
    "ReqId",
    "ErrorCode",
    "ZeusClientError",
    "CatalogError",
    "SessionHandle",
    "SessionHashChoice",
    "ContractService",
    "compute_contract_hash",
    "extract_stamped_hash",
    "resolve_session_contract_hash",
    "heal_trailing_ws_stamp_drift",
    "LoadedCatalog",
    "chat_request_filename",
    "merge_scope_brief",
    "resolve_catalog_path",
    "scope_chat_requests_subdir",
]
