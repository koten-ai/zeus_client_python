"""Public catalog facade on ZeusRuntime — load / list / sync / contract / mini_schema."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.application import catalog_brief as catalog_brief_uc
from zeus_client.application.catalog_sync import SyncResult, sync_catalogs
from zeus_client.domain.catalog import (
    LoadedCatalog,
    catalog_entry_stats,
    extract_scope_brief,
)
from zeus_client.domain.contract import compute_contract_hash, extract_stamped_hash
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.domain.floor import assert_floor_allows
from zeus_client.domain.mini_schema import get_mini_schema
from zeus_client.ports import CatalogKey

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

logger = logging.getLogger("zeus_client.catalog")

__all__ = ["CatalogAPI", "CatalogContractAPI", "CatalogMiniSchemaAPI"]


class CatalogContractAPI:
    """``catalog.contract.hash`` / ``id`` / ``bind`` / ``compute_local``."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    def hash(self, doc: Mapping[str, Any]) -> str:
        stamped = extract_stamped_hash(dict(doc))
        if not stamped:
            raise CatalogError(
                code=ErrorCode.CONTRACT_HASH_MISSING,
                component="api.catalog.contract",
                public_message="contract hash missing on stamped catalog",
            )
        return stamped

    def id(self, doc: Mapping[str, Any]) -> str:
        cb = doc.get("contract") if isinstance(doc, Mapping) else None
        if isinstance(cb, Mapping):
            cid = str(cb.get("id") or "").strip()
            if cid:
                return cid
        return ""

    def compute_local(self, doc: Mapping[str, Any]) -> str:
        """Diagnostics only — never a production stamp."""
        return compute_contract_hash(dict(doc))

    def bind(
        self,
        bucket: str,
        scope: str,
        mode: str,
        doc: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Prefer published stamp; fall back to config scope_contracts. Never invent."""
        stamped = extract_stamped_hash(dict(doc)) if isinstance(doc, Mapping) else ""
        cid = self.id(doc) if isinstance(doc, Mapping) else ""
        bound_id, bound_hash = _scope_contract_entry(
            self._rt.config.scope_contracts, bucket, scope, mode
        )
        if stamped:
            return {
                "contract_id": cid or bound_id,
                "contract_hash": stamped,
                "hash_source": "stamp",
            }
        if bound_hash:
            return {
                "contract_id": cid or bound_id,
                "contract_hash": bound_hash,
                "hash_source": "bound",
            }
        raise CatalogError(
            code=ErrorCode.CONTRACT_HASH_MISSING,
            component="api.catalog.contract",
            public_message="no stamped or bound contract_hash (invent forbidden)",
            details={"bucket": bucket, "scope": scope, "mode": mode},
        )


class CatalogMiniSchemaAPI:
    """``catalog.mini_schema.get`` / ``from_catalog``."""

    def __init__(self, runtime: ZeusRuntime, parent: CatalogAPI) -> None:
        self._rt = runtime
        self._parent = parent

    def from_catalog(
        self,
        doc: Mapping[str, Any] | str | Path,
        *,
        values: bool = False,
    ) -> dict[str, Any]:
        parsed = get_mini_schema(doc, values=values)
        return {**parsed, "source": "disk"}

    async def get(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
        values: bool = False,
        live: bool = True,
        base_id: str | None = None,
    ) -> dict[str, Any]:
        t = target or self._rt.config.target
        m = mode or self._rt.config.settings.mode or "analytics"
        req_id = ""
        if live:
            remote = self._parent._remote()
            if remote is not None:
                try:
                    headers = await self._parent._auth_headers(t)
                    body = await remote.fetch_chat_request(t.bucket, t.scope, m, headers=headers)
                    req_id = str(getattr(remote, "last_req_id", "") or "")
                    parsed = get_mini_schema(body, values=values)
                    return {**parsed, "source": "live", "req_id": req_id}
                except Exception as exc:  # noqa: BLE001 — fall back to disk
                    logger.info("catalog.mini_schema.live_failed: %s", exc)
        try:
            loaded = await self._parent.load(m, target=t, base_id=base_id)
        except CatalogError:
            return {"scope": "", "mode": "", "entity_types": {}, "source": "disk", "req_id": req_id}
        parsed = get_mini_schema(loaded.body, values=values)
        return {**parsed, "source": "disk", "req_id": req_id}


def _scope_contract_entry(
    contracts: Mapping[str, Any],
    bucket: str,
    scope: str,
    mode: str,
) -> tuple[str, str]:
    if not isinstance(contracts, Mapping):
        return "", ""
    entry = contracts.get(f"{bucket}/{scope}") or contracts.get(f"{bucket}.{scope}") or {}
    if not isinstance(entry, Mapping):
        return "", ""
    mode_ent = entry.get(mode) or entry
    if not isinstance(mode_ent, Mapping):
        return "", ""
    cid = str(mode_ent.get("contract_id") or mode_ent.get("id") or "").strip()
    ch = str(mode_ent.get("contract_hash") or mode_ent.get("hash") or "").strip()
    if "TO_BE_FILLED" in ch:
        ch = ""
    return cid, ch


class CatalogAPI:
    """``rt.catalog.load`` / ``list`` / ``info`` / ``sync`` / ``contract`` / ``mini_schema``."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime
        self.contract = CatalogContractAPI(runtime)
        self.mini_schema = CatalogMiniSchemaAPI(runtime, self)

    def _remote(self) -> Any:
        """Configured catalog remote, or a lazy HTTP client when Zeus is real."""
        remote = getattr(self._rt.services, "catalog_remote", None)
        if remote is not None:
            return remote
        zeus = self._rt.services.zeus
        if zeus is None:
            return None
        from zeus_client.adapters.zeus_http.verbs import HttpxZeusPort

        if not isinstance(zeus, HttpxZeusPort):
            return None
        endpoint = self._rt.config.zeus
        if not endpoint.url:
            return None
        from zeus_client.adapters.zeus_http.catalog_remote import HttpxCatalogRemote

        remote = HttpxCatalogRemote(endpoint=endpoint, secrets=self._rt.services.secrets)
        self._rt.services.catalog_remote = remote
        return remote

    async def _auth_headers(self, target: Any) -> dict[str, str]:
        zeus = self._rt.services.zeus
        resolve = getattr(zeus, "resolve_auth", None) if zeus is not None else None
        if resolve is None:
            return {}
        try:
            ctx = await resolve(target)
            return dict(getattr(ctx, "headers", None) or {})
        except Exception as exc:  # noqa: BLE001 — fetch may still succeed
            logger.info("catalog.auth_headers_failed: %s", exc)
            return {}

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

    def _key(
        self,
        mode: str | None = None,
        target: Any = None,
        base_id: str | None = None,
    ) -> CatalogKey:
        t = target or self._rt.config.target
        m = mode or self._rt.config.settings.mode or "analytics"
        return CatalogKey(mode=m, bucket=t.bucket, scope=t.scope, base_id=base_id)

    async def load(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
        base_id: str | None = None,
    ) -> LoadedCatalog:
        store = self._store()
        loaded = store.load_rich(self._key(mode, target, base_id))
        assert_floor_allows(
            client_floor=self._rt.config.client_floor,
            base_id=loaded.base_id or base_id,
            allow_degraded=self._rt.config.allow_degraded_catalog,
        )
        from zeus_client.observability.logging import get_family_logger

        get_family_logger().info(
            "zeus_client.catalog.loaded",
            **{
                "base_id": loaded.base_id or "",
                "client.floor": self._rt.config.client_floor,
                "source": loaded.source,
                "result": "ok",
            },
        )
        logger.info(
            "zeus_client.catalog.loaded base_id=%s client.floor=%s source=%s stamp_present=%s",
            loaded.base_id or "",
            self._rt.config.client_floor,
            loaded.source,
            "true" if loaded.contract_hash else "false",
        )
        return loaded

    async def ensure_scope_brief(
        self,
        doc: Mapping[str, Any] | None,
        *,
        target: Any = None,
        mode: str | None = None,
    ) -> catalog_brief_uc.ScopeBriefResult:
        """Borrow live ``## SCOPE BRIEF`` when the catalog has none."""
        t = target or self._rt.config.target
        m = mode or self._rt.config.settings.mode or "analytics"
        remote = self._remote()

        async def _fetch(bucket: str, scope: str, mode_name: str) -> dict[str, Any]:
            headers = await self._auth_headers(t)
            body = await remote.fetch_chat_request(  # type: ignore[union-attr]
                bucket, scope, mode_name, headers=headers
            )
            return dict(body) if not isinstance(body, dict) else body

        result = await catalog_brief_uc.ensure_scope_brief(
            doc,
            fetch=_fetch if remote is not None else None,
            bucket=t.bucket,
            scope=t.scope,
            mode=m,
        )
        req_id = ""
        if remote is not None:
            req_id = str(getattr(remote, "last_req_id", "") or "")
        if req_id and result.req_id != req_id:
            result = replace(result, req_id=req_id)
        if result.merged:
            logger.info(
                "zeus_client.catalog.scope_brief.merged mode=%s req_id=%s",
                m,
                req_id,
            )
        elif result.note != "scope_brief: already present":
            logger.info("zeus_client.catalog.scope_brief %s", result.note)
        return result

    async def load_for_turn(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
        base_id: str | None = None,
    ) -> LoadedCatalog:
        """Disk load plus optional live SCOPE BRIEF merge for an agent turn."""
        loaded = await self.load(mode, target=target, base_id=base_id)
        result = await self.ensure_scope_brief(loaded.body, target=target, mode=mode)
        source = loaded.source
        if result.merged:
            source = f"{source} + live scope brief"
        elif result.note and not extract_scope_brief(result.body):
            source = f"{source}; {result.note}"
        return replace(loaded, body=result.body, source=source)

    async def load_pin(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
    ) -> LoadedCatalog:
        """Load the configured pin-era pack.

        Uses ``RuntimeConfig.production_base_id`` when set (human-copied COMPAT
        id only). Does not invent a default production pin — callers/tests pass
        ``base_id`` via ``load`` when the config field is null.
        """
        pin = (self._rt.config.production_base_id or "").strip()
        if not pin:
            raise CatalogError(
                code=ErrorCode.CATALOG_NOT_FOUND,
                component="api.catalog",
                public_message=(
                    "production_base_id unset; pass base_id= to catalog.load "
                    "or set production_base_id from chat_request COMPAT + Hub stamp"
                ),
            )
        return await self.load(mode, target=target, base_id=pin)

    async def list(self) -> list[dict[str, str]]:
        return self._store().list_entries()

    async def info(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
        base_id: str | None = None,
    ) -> dict[str, str]:
        """Metadata / lineage / stamp present / verb count — no full body dump."""
        loaded = await self.load(mode, target=target, base_id=base_id)
        from pathlib import Path

        stats = catalog_entry_stats(
            Path(loaded.path) if loaded.path else Path("."),
            loaded.body,
        )
        return {
            "mode": mode or self._rt.config.settings.mode or "analytics",
            "base_id": loaded.base_id or stats["base_id"],
            "lineage_id": loaded.lineage_id or stats["lineage_id"],
            "stamp_present": stats["stamp_present"],
            "verb_count": stats["verb_count"],
            "contract_id": stats["contract_id"],
            "source": loaded.source,
            "path": loaded.path or "",
            "client_floor": self._rt.config.client_floor,
            "envelope": str(loaded.body.get("_format") or ""),
            "has_response_schema": "true" if loaded.response_output_schema else "false",
        }

    async def scope_brief_get(
        self,
        mode: str | None = None,
        *,
        target: Any = None,
        live: bool = True,
    ) -> dict[str, str]:
        """Live or disk ``## SCOPE BRIEF`` text."""
        t = target or self._rt.config.target
        m = mode or self._rt.config.settings.mode or "analytics"
        source = "disk"
        req_id = ""
        text = ""
        if live:
            remote = self._remote()
            if remote is not None:
                try:
                    headers = await self._auth_headers(t)
                    body = await remote.fetch_chat_request(t.bucket, t.scope, m, headers=headers)
                    text = extract_scope_brief(body)
                    source = "live"
                    req_id = str(getattr(remote, "last_req_id", "") or "")
                except Exception as exc:  # noqa: BLE001
                    logger.info("catalog.scope_brief.live_failed: %s", exc)
        if not text:
            loaded = await self.load(m, target=t)
            text = extract_scope_brief(loaded.body)
        return {"text": text, "source": source, "req_id": req_id}

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
            remote = self._remote()
            if remote is None:
                raise CatalogError(
                    code=ErrorCode.CATALOG_SYNC_FAILED,
                    component="api.catalog",
                    public_message="catalog sync requires fetch= or services.catalog_remote",
                )

            async def _fetch(bucket: str, scope: str, mode: str) -> dict:
                from zeus_client.config.models import DataTarget

                headers = await self._auth_headers(DataTarget(bucket=bucket, scope=scope))
                result = await remote.fetch_chat_request(bucket, scope, mode, headers=headers)
                return dict(result) if not isinstance(result, dict) else result

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
