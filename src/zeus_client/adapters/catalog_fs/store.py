"""Filesystem catalog store — fail-closed path resolution + atomic writes."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from zeus_client.domain.catalog import (
    MANIFEST_NAME,
    LoadedCatalog,
    chat_request_filename,
    check_lineage,
    lineage_base_id,
    list_catalog_entries,
    path_source_label,
    prepare_loaded_document,
    resolve_catalog_path,
    scope_chat_requests_subdir,
)
from zeus_client.domain.contract import extract_stamped_hash
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.domain.pack_schema import load_sibling_pack_schema
from zeus_client.ports import CatalogDocument, CatalogKey

__all__ = ["FsCatalogStore"]


class FsCatalogStore:
    """``CatalogStorePort`` over a user chat_requests root (+ optional bundled)."""

    def __init__(
        self,
        root: str | Path,
        *,
        bundled_dir: str | Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.bundled_dir = Path(bundled_dir) if bundled_dir is not None else None

    def resolve_path(self, key: CatalogKey) -> Path | None:
        return resolve_catalog_path(
            mode=key.mode,
            bucket=key.bucket,
            scope=key.scope,
            user_dir=self.root,
            bundled_dir=self.bundled_dir,
            base_id=key.base_id,
        )

    def load(self, key: CatalogKey) -> CatalogDocument:
        path = self.resolve_path(key)
        if path is None:
            raise CatalogError(
                code=ErrorCode.CATALOG_NOT_FOUND,
                component="adapters.catalog_fs",
                public_message=(
                    f"catalog not found for mode={key.mode!r} "
                    f"base_id={key.base_id!r} "
                    f"scope={key.bucket}/{key.scope}; "
                    f"expected under {self.root / scope_chat_requests_subdir(key.bucket, key.scope)} "
                    f"or top-level {self.root / chat_request_filename(key.mode, key.base_id)}"
                    + (f" or bundled {self.bundled_dir}" if self.bundled_dir is not None else "")
                ),
                details={
                    "mode": key.mode,
                    "base_id": key.base_id,
                    "bucket": key.bucket,
                    "scope": key.scope,
                    "user_dir": str(self.root),
                },
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CatalogError(
                code=ErrorCode.CATALOG_PARSE_FAILED,
                component="adapters.catalog_fs",
                public_message=f"catalog parse failed: {path.name}",
                details={"path": str(path), "error": str(e)},
            ) from e
        except OSError as e:
            raise CatalogError(
                code=ErrorCode.CATALOG_NOT_FOUND,
                component="adapters.catalog_fs",
                public_message=f"catalog unreadable: {path}",
                details={"path": str(path), "error": str(e)},
            ) from e

        body = prepare_loaded_document(raw if isinstance(raw, dict) else {})
        if key.base_id:
            check_lineage(
                body,
                key.base_id,
                require_lineage=True,
                path_name=path.name,
            )
        stamped = extract_stamped_hash(body)
        return CatalogDocument(
            body=body,
            path=str(path),
            contract_hash=stamped or None,
        )

    def load_rich(self, key: CatalogKey) -> LoadedCatalog:
        """Load with source label (API convenience)."""
        doc = self.load(key)
        path = Path(doc.path) if doc.path else None
        source = (
            path_source_label(path, user_dir=self.root, bundled_dir=self.bundled_dir)
            if path is not None
            else "unknown"
        )
        body = dict(doc.body)
        lineage = lineage_base_id(body)
        schema, example = load_sibling_pack_schema(doc.path)
        return LoadedCatalog(
            body=body,
            path=doc.path,
            source=source,
            contract_hash=doc.contract_hash,
            base_id=key.base_id or lineage,
            lineage_id=lineage,
            response_output_schema=schema,
            response_output_example=example,
        )

    def save(self, key: CatalogKey, doc: CatalogDocument) -> None:
        """Write catalog into the **scope** subdir under root (never sibling guess)."""
        scope_dir = self.root / scope_chat_requests_subdir(key.bucket, key.scope)
        filename = chat_request_filename(key.mode, key.base_id)
        out = scope_dir / filename
        body = dict(doc.body) if isinstance(doc.body, Mapping) else {}
        self._atomic_write_json(out, body)

    def scope_path(self, key: CatalogKey) -> Path:
        return (
            self.root
            / scope_chat_requests_subdir(key.bucket, key.scope)
            / chat_request_filename(key.mode, key.base_id)
        )

    def list_entries(self) -> list[dict[str, str]]:
        return list_catalog_entries(self.root, self.bundled_dir)

    @staticmethod
    def _atomic_write_json(path: Path, doc: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def write_manifest(self, payload: dict[str, Any]) -> Path:
        path = self.root / MANIFEST_NAME
        self._atomic_write_json(path, payload)
        return path

    def load_manifest(self) -> dict[str, Any]:
        path = self.root / MANIFEST_NAME
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
