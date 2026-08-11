"""Secret store port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["SecretStorePort"]


@runtime_checkable
class SecretStorePort(Protocol):
    def get(self, name: str) -> str | None: ...
