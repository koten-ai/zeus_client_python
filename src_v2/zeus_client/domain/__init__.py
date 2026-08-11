"""Domain package — pure types, no httpx/provider SDKs."""

from __future__ import annotations

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
]
