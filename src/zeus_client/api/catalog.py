"""Public catalog facade on ZeusRuntime — load / list / sync."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.application.catalog_sync import SyncResult, sync_catalogs
from zeus_client.domain.catalog import LoadedCatalog
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.ports import CatalogKey

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["CatalogAPI"]


class CatalogAPI:
    """``rt.catalog.load`` / ``list`` / ``sync``."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    def _store(self) -> FsCatalogStore:
        cat = self._rt.services.catalog
        if isinstance(cat, FsCatalogStore):
            return cat
        # Lazy default from config
        root = self._rt.config.chat_requests_dir
        if not root:
            raise CatalogError(
                code=ErrorCode.CATALOG_NOT_FOUND,
                component="api.catalog",
                public_message=(
                    "catalog store not wired and RuntimeConfig.chat_requests_dir is unset"
                ),
            )
        store = FsCatalogStore(root=root)
        self._rt.services.catalog = store
        return store

    def _key(self, mode: str | None = None, target: Any = None) -> CatalogKey:
        t = target or self._rt.config.target
        m = mode or self._rt.config.settings.mode or "analytics"
        return CatalogKey(mode=m, bucket=t.bucket, scope=t.scope)

    async def load(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
    ) -> LoadedCatalog:
        store = self._store()
        return store.load_rich(self._key(mode, target))

    async def list(self) -> list[dict[str, str]]:
        return self._store().list_entries()

    async def sync(
        self,
        *,
        force: bool = False,
        cfg: Mapping[str, Any] | None = None,
        fetch: Any = None,
    ) -> SyncResult:
        """Sync catalogs. Requires ``fetch`` coroutine or a remote on services."""
        store = self._store()
        if fetch is None:
            remote = getattr(self._rt.services, "catalog_remote", None)
            if remote is None:
                raise CatalogError(
                    code=ErrorCode.CATALOG_SYNC_FAILED,
                    component="api.catalog",
                    public_message="catalog sync requires fetch= or services.catalog_remote",
                )

            async def _fetch(bucket: str, scope: str, mode: str) -> dict:
                return await remote.fetch_chat_request(bucket, scope, mode)

            fetch = _fetch

        sync_cfg: Mapping[str, Any]
        if cfg is not None:
            sync_cfg = cfg
        else:
            # Minimal cfg from RuntimeConfig target
            t = self._rt.config.target
            sync_cfg = {
                "samples": {
                    "default": {
                        "bucket": t.bucket,
                        "scope": t.scope,
                    }
                },
                "chat_requests_sync": {
                    "modes": [self._rt.config.settings.mode or "analytics"],
                },
            }

        return await sync_catalogs(sync_cfg, store=store, fetch=fetch, force=force)
