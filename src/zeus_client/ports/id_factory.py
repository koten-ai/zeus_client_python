"""Default UUID-based IdFactory."""

from __future__ import annotations

import uuid
from typing import Protocol

__all__ = ["IdFactory", "UuidIdFactory"]


class IdFactory(Protocol):
    def turn_id(self) -> str: ...

    def chat_id(self) -> str: ...

    def call_id(self) -> str: ...

    def span_id(self) -> str: ...


class UuidIdFactory:
    def turn_id(self) -> str:
        return str(uuid.uuid4())

    def chat_id(self) -> str:
        return str(uuid.uuid4())

    def call_id(self) -> str:
        return str(uuid.uuid4())

    def span_id(self) -> str:
        return uuid.uuid4().hex[:16]
