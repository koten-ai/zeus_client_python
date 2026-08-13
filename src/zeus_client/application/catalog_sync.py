"""Catalog sync use-case — preserve consistent local stamps (ZCM-010)."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.domain.catalog import MANIFEST_NAME, chat_request_filename
from zeus_client.domain.contract import compute_contract_hash, extract_stamped_hash
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.ports import CatalogDocument, CatalogKey

__all__ = [
    "SyncResult",
    "resolve_sync_scopes",
    "resolve_sync_modes",
    "should_preserve_local_catalog",
    "sync_catalogs",
    "doc_fingerprint",
]

_MANIFEST_VERSION = 1

FetchFn = Callable[[str, str, str], Awaitable[dict[str, Any]]]


@dataclass
class SyncResult:
    synced: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    manifest_path: Path | None = None


def _dedupe_scopes(scopes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for bucket, scope in scopes:
        key = (bucket, scope)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def resolve_sync_scopes(cfg: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Resolve (bucket, scope) pairs from config (samples / contracts / explicit)."""
    sync_cfg = cfg.get("chat_requests_sync") or {}
    scopes_spec = sync_cfg.get("scopes", "from_samples")

    if scopes_spec == "from_samples":
        out: list[tuple[str, str]] = []
        for sample in (cfg.get("samples") or {}).values():
            if not isinstance(sample, Mapping):
                continue
            bucket = str(sample.get("bucket") or "").strip()
            scope = str(sample.get("scope") or "").strip()
            if bucket and scope:
                out.append((bucket, scope))
        return sorted(_dedupe_scopes(out))

    if scopes_spec == "from_contracts":
        out = []
        contracts = cfg.get("scope_contracts") or {}
        # also accept nested under zeus
        if not contracts and isinstance(cfg.get("zeus"), Mapping):
            contracts = cfg["zeus"].get("scope_contracts") or {}
        for key in contracts:
            if "/" in str(key):
                bucket, scope = str(key).split("/", 1)
            else:
                bucket, scope = str(key), "_default"
            if bucket and scope:
                out.append((bucket, scope))
        return sorted(_dedupe_scopes(out))

    if isinstance(scopes_spec, list):
        out = []
        for item in scopes_spec:
            if isinstance(item, str) and "/" in item:
                bucket, scope = item.split("/", 1)
                if bucket and scope:
                    out.append((bucket, scope))
        return sorted(_dedupe_scopes(out))

    return resolve_sync_scopes({**dict(cfg), "chat_requests_sync": {"scopes": "from_samples"}})


def resolve_sync_modes(
    cfg: Mapping[str, Any],
    bucket: str,
    scope: str,
) -> list[str]:
    """Modes to sync for a scope — auto = default + scope_contracts keys."""
    sync_cfg = cfg.get("chat_requests_sync") or {}
    modes_spec = sync_cfg.get("modes", "auto")
    if isinstance(modes_spec, list):
        modes = sorted({str(m).strip() for m in modes_spec if str(m).strip()})
        return modes or _auto_modes(cfg, bucket, scope)
    if modes_spec == "auto":
        return _auto_modes(cfg, bucket, scope)
    return _auto_modes(cfg, bucket, scope)


def _auto_modes(cfg: Mapping[str, Any], bucket: str, scope: str) -> list[str]:
    modes: set[str] = {"default"}
    scope_key = f"{bucket}/{scope}"
    contracts: Mapping[str, Any] = {}
    if isinstance(cfg.get("scope_contracts"), Mapping):
        contracts = cfg["scope_contracts"]  # type: ignore[assignment]
    elif isinstance(cfg.get("zeus"), Mapping):
        contracts = cfg["zeus"].get("scope_contracts") or {}  # type: ignore[index]
    entry = contracts.get(scope_key) or {}
    if isinstance(entry, Mapping):
        for key in entry:
            if key:
                modes.add(str(key))
    return sorted(modes, key=lambda m: (0 if m == "default" else 1, m))


def doc_fingerprint(doc: dict) -> str:
    try:
        return compute_contract_hash(doc)
    except Exception:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _is_stamped_standardized(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    if not extract_stamped_hash(doc):
        return False
    return bool(doc.get("verbs") or doc.get("_format") == "zeus.chat_request.v2")


def _is_legacy_tools_catalog(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    if extract_stamped_hash(doc):
        return False
    if doc.get("verbs") or doc.get("_format") == "zeus.chat_request.v2":
        return False
    return bool(doc.get("tools"))


def _stamp_consistent(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    stamped = extract_stamped_hash(doc)
    if not stamped:
        return False
    try:
        return stamped == compute_contract_hash(doc)
    except Exception:
        return False


def should_preserve_local_catalog(local_doc: dict, remote_doc: dict) -> str:
    """Return skip reason when a good local snapshot must not be clobbered.

    - Preserve Verify-stamped V2 local over unstamped tools-only remote.
    - Preserve stamp-consistent local when remote stamp disagrees with content.
    """
    if not _is_stamped_standardized(local_doc):
        return ""
    if _is_legacy_tools_catalog(remote_doc):
        return "preserve_stamped_local (remote is unstamped tools-only / V1-shaped)"
    if not extract_stamped_hash(remote_doc):
        return "preserve_stamped_local (remote has no embedded contract hash)"
    if _stamp_consistent(local_doc) and not _stamp_consistent(remote_doc):
        return (
            "preserve_stamped_local (remote embedded stamp disagrees with "
            "content hash; keep consistent local Verify stamp)"
        )
    return ""


def _manifest_key(bucket: str, scope: str, mode: str) -> str:
    return f"{bucket}/{scope}/{mode}"


async def sync_catalogs(
    cfg: Mapping[str, Any],
    *,
    store: FsCatalogStore,
    fetch: FetchFn,
    force: bool = False,
    modes: Sequence[str] | None = None,
    scopes: Sequence[tuple[str, str]] | None = None,
) -> SyncResult:
    """Pull remote catalogs into the FS store with preserve-local rules."""
    store.root.mkdir(parents=True, exist_ok=True)
    prior = store.load_manifest()
    prior_files = prior.get("files") if isinstance(prior.get("files"), dict) else {}

    scope_list = list(scopes) if scopes is not None else resolve_sync_scopes(cfg)
    if not scope_list:
        raise CatalogError(
            code=ErrorCode.CATALOG_SYNC_FAILED,
            component="application.catalog_sync",
            public_message="no scopes configured for chat_requests sync",
        )

    result = SyncResult(manifest_path=store.root / MANIFEST_NAME)
    next_files: dict[str, dict] = dict(prior_files)

    for bucket, scope in scope_list:
        mode_list = list(modes) if modes is not None else resolve_sync_modes(cfg, bucket, scope)
        for mode in mode_list:
            key = _manifest_key(bucket, scope, mode)
            cat_key = CatalogKey(mode=mode, bucket=bucket, scope=scope)
            out = store.scope_path(cat_key)
            try:
                doc = await fetch(bucket, scope, mode)
                if not isinstance(doc, dict):
                    raise RuntimeError("remote catalog is not an object")
                doc_hash = doc_fingerprint(doc)
                prev_raw = prior_files.get(key)
                prev: dict[str, Any] = prev_raw if isinstance(prev_raw, dict) else {}

                local_doc: dict | None = None
                if out.is_file():
                    try:
                        local_doc = json.loads(out.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        local_doc = None

                if isinstance(local_doc, dict):
                    preserve_reason = should_preserve_local_catalog(local_doc, doc)
                    if preserve_reason:
                        rel_existing = (
                            str(out.relative_to(store.root))
                            if out.is_file()
                            else chat_request_filename(mode)
                        )
                        result.skipped.append(
                            {
                                "scope": f"{bucket}/{scope}",
                                "mode": mode,
                                "path": rel_existing,
                                "hash": prev.get("hash") or doc_fingerprint(local_doc),
                                "reason": preserve_reason,
                            }
                        )
                        continue

                if (
                    not force
                    and prev.get("hash") == doc_hash
                    and out.is_file()
                    and prev.get("path") == str(out.relative_to(store.root))
                ):
                    result.skipped.append(
                        {
                            "scope": f"{bucket}/{scope}",
                            "mode": mode,
                            "path": str(out.relative_to(store.root)),
                            "hash": doc_hash,
                        }
                    )
                    continue

                store.save(cat_key, CatalogDocument(body=doc, path=str(out)))
                rel = str(out.relative_to(store.root))
                entry = {
                    "scope": f"{bucket}/{scope}",
                    "mode": mode,
                    "path": rel,
                    "hash": doc_hash,
                }
                result.synced.append(entry)
                next_files[key] = {**entry, "synced_at": time.time()}
            except Exception as e:
                result.errors.append(
                    {
                        "scope": f"{bucket}/{scope}",
                        "mode": mode,
                        "error": str(e),
                    }
                )

    manifest = {
        "version": _MANIFEST_VERSION,
        "synced_at": time.time(),
        "files": next_files,
    }
    result.manifest_path = store.write_manifest(manifest)
    return result
