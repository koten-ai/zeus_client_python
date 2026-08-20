"""Typed identity wrappers for V2 domain (Turn / Chat / Call / Session / Req)."""

from __future__ import annotations

import re
import uuid
from typing import TypeVar

__all__ = [
    "TurnId",
    "ChatId",
    "CallId",
    "SessionId",
    "ReqId",
    "UUID_V4_RE",
    "new_id",
    "new_zeus_req_id",
    "new_trace_id",
    "is_uuid_v4",
]

# RFC 4122 UUID v4: version nibble 4, variant 8|9|a|b. Lowercase hyphenated.
UUID_V4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


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


def new_zeus_req_id() -> str:
    """RFC 4122 UUID v4 (lowercase hyphenated) — family mint for req/chat/turn/call."""
    return str(uuid.uuid4())


def new_trace_id() -> str:
    """W3C 32-hex trace id (not a Zeus req_id)."""
    return uuid.uuid4().hex


def is_uuid_v4(value: str | None) -> bool:
    return bool(UUID_V4_RE.match(str(value or "").strip()))


def new_id(cls: type[T], *, prefix: str = "") -> T:
    """Mint a unique id of the given wrapper type.

    Default (no prefix) is a canonical UUID v4. A prefix is kept for tests
    that need a namespaced string; it is **not** a Zeus ``req_id``.
    """
    if prefix:
        return cls(f"{prefix}{uuid.uuid4().hex}")
    return cls(new_zeus_req_id())
