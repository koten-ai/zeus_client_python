"""Domain package — pure types, no httpx/provider SDKs."""

from __future__ import annotations

from zeus_client_v2.domain.contract import (
    ContractService,
    SessionHashChoice,
    compute_contract_hash,
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
    resolve_session_contract_hash,
)
from zeus_client_v2.domain.errors import ErrorCode, ZeusClientError
from zeus_client_v2.domain.ids import CallId, ChatId, ReqId, SessionId, TurnId

__all__ = [
    "TurnId",
    "ChatId",
    "CallId",
    "SessionId",
    "ReqId",
    "ErrorCode",
    "ZeusClientError",
    "SessionHashChoice",
    "ContractService",
    "compute_contract_hash",
    "extract_stamped_hash",
    "resolve_session_contract_hash",
    "heal_trailing_ws_stamp_drift",
]
