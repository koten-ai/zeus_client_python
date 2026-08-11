"""Catalog filesystem / store port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from zeus_client_v2.ports import CatalogDocument, CatalogKey

__all__ = ["CatalogStorePort"]


@runtime_checkable
class CatalogStorePort(Protocol):
    def load(self, key: CatalogKey) -> CatalogDocument: ...

    def save(self, key: CatalogKey, doc: CatalogDocument) -> None: ...
