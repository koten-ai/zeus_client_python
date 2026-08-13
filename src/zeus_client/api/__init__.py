"""API facade package."""

from __future__ import annotations

from zeus_client.api.catalog import CatalogAPI
from zeus_client.api.data import DataAPI

__all__ = ["CatalogAPI", "DataAPI"]
