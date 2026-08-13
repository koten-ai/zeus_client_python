"""Typed identity wrappers for V2 domain (Turn / Chat / Call / Session / Req)."""

from __future__ import annotations

import uuid
from typing import TypeVar

__all__ = [
    "TurnId",
    "ChatId",
    "CallId",
    "SessionId",
    "ReqId",
    "new_id",
]


class _Id(str):
    """Frozen str newtype-style wrapper; empty values rejected."""

    __slots__ = ()

    def __new__(cls, value: str) -> _Id:
        if not isinstance(value, str):
            raise TypeError(f"{cls.__name__} requires str, got {type(value).__name__}")
        text = value.strip()
        if not text:
            raise ValueError(f"{cls.__name__} must be non-empty")
        return str.__new__(cls, text)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str.__repr__(self)})"


class TurnId(_Id):
    """Client-minted id for one agent/direct turn."""

    __slots__ = ()


class ChatId(_Id):
    """Logical chat / conversation id (may span turns)."""

    __slots__ = ()


class CallId(_Id):
    """Single LLM or tool call id within a turn."""

    __slots__ = ()


class SessionId(_Id):
    """Zeus durable session id (server-minted when durable sessions on)."""

    __slots__ = ()


class ReqId(_Id):
    """Zeus hop correlation id (prefer server ``X-Zeus-Req-Id``)."""

    __slots__ = ()


T = TypeVar("T", bound=_Id)


def new_id(cls: type[T], *, prefix: str = "") -> T:
    """Mint a unique id of the given wrapper type (UUID4 hex suffix)."""
    return cls(f"{prefix}{uuid.uuid4().hex}")
