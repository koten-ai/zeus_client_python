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
        return f"turn_{uuid.uuid4().hex}"

    def chat_id(self) -> str:
        return f"chat_{uuid.uuid4().hex}"

    def call_id(self) -> str:
        return f"call_{uuid.uuid4().hex}"

    def span_id(self) -> str:
        return f"span_{uuid.uuid4().hex[:16]}"
