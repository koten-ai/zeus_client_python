"""Domain package — pure types, no httpx/provider SDKs."""

from __future__ import annotations

from zeus_client.domain.catalog import (
    LoadedCatalog,
    catalog_filenames_for_mode,
    chat_request_filename,
    merge_scope_brief,
    resolve_catalog_path,
    scope_chat_requests_subdir,
)
from zeus_client.domain.contract import (
    ContractService,
    SessionHashChoice,
    compute_contract_hash,
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
    resolve_session_contract_hash,
)
from zeus_client.domain.errors import CatalogError, ErrorCode, ZeusClientError
from zeus_client.domain.ids import (
    CallId,
    ChatId,
    ReqId,
    SessionId,
    TurnId,
    is_uuid_v4,
    new_zeus_req_id,
)
from zeus_client.domain.layer_a import (
    LayerA,
    parse_layer_a,
    peel_layer_a_summary,
    user_facing_answer,
)
from zeus_client.domain.policy import PolicyDecision, decide_policy
from zeus_client.domain.session import SessionHandle
from zeus_client.domain.stamps import PRODUCT_USER, product_stamp

__all__ = [
    "TurnId",
    "ChatId",
    "CallId",
    "SessionId",
    "ReqId",
    "new_zeus_req_id",
    "is_uuid_v4",
    "PRODUCT_USER",
    "product_stamp",
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
    "catalog_filenames_for_mode",
    "chat_request_filename",
    "merge_scope_brief",
    "resolve_catalog_path",
    "scope_chat_requests_subdir",
    "LayerA",
    "parse_layer_a",
    "peel_layer_a_summary",
    "user_facing_answer",
    "PolicyDecision",
    "decide_policy",
]
