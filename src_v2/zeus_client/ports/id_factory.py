"""IdFactory port — mint turn/chat/call/span identifiers."""

from __future__ import annotations

from typing import Protocol


class IdFactory(Protocol):
    def turn_id(self) -> str: ...

    def chat_id(self) -> str: ...

    def call_id(self) -> str: ...

    def span_id(self) -> str: ...


__all__ = ["IdFactory"]
