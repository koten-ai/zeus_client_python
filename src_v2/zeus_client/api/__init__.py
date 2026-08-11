"""API facade package."""

from __future__ import annotations

from zeus_client_v2.api.catalog import CatalogAPI
from zeus_client_v2.api.data import DataAPI

__all__ = ["CatalogAPI", "DataAPI"]
