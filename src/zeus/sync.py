"""Sync chat_request catalogs from Zeus into the user config directory."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from zeus_client.config import resolve_zeus_config
from zeus_client.constants import scope_chat_requests_subdir, user_chat_requests_dir
from zeus_client.contract_hash import compute_contract_hash
from zeus_client.logging_setup import logger
from zeus_client.zeus.auth import resolve_zeus_auth
from zeus_client.zeus.catalog import (
    _MANIFEST_NAME,
    chat_request_filename,
    fetch_scope_chat_request,
    modes_to_bootstrap,
)

_MANIFEST_VERSION = 1


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


def resolve_sync_scopes(cfg: dict, zcfg: dict) -> list[tuple[str, str]]:
    sync_cfg = cfg.get("chat_requests_sync") or {}
    scopes_spec = sync_cfg.get("scopes", "from_samples")

    if scopes_spec == "from_samples":
        out: list[tuple[str, str]] = []
        for sample in (cfg.get("samples") or {}).values():
            bucket = (sample.get("bucket") or "").strip()
            scope = (sample.get("scope") or "").strip()
            if bucket and scope:
                out.append((bucket, scope))
        return sorted(_dedupe_scopes(out))

    if scopes_spec == "from_contracts":
        out = []
        for key in (zcfg.get("scope_contracts") or {}):
            if "/" in key:
                bucket, scope = key.split("/", 1)
            else:
                bucket, scope = key, "_default"
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

    return resolve_sync_scopes({**cfg, "chat_requests_sync": {"scopes": "from_samples"}}, zcfg)


def resolve_sync_modes(cfg: dict, bucket: str, scope: str) -> list[str]:
    sync_cfg = cfg.get("chat_requests_sync") or {}
    modes_spec = sync_cfg.get("modes", "auto")
    if modes_spec == "auto":
        return modes_to_bootstrap(cfg, bucket, scope)
    if isinstance(modes_spec, list):
        modes = sorted({str(m).strip() for m in modes_spec if str(m).strip()})
        return modes or modes_to_bootstrap(cfg, bucket, scope)
    return modes_to_bootstrap(cfg, bucket, scope)


def _load_manifest(dest: Path) -> dict:
    path = dest / _MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_manifest(path: Path, payload: dict) -> None:
    _atomic_write_json(path, payload)


def _manifest_key(bucket: str, scope: str, mode: str) -> str:
    return f"{bucket}/{scope}/{mode}"


def _doc_fingerprint(doc: dict) -> str:
    try:
        return compute_contract_hash(doc)
    except Exception:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"))


async def sync_chat_requests(
    cfg: dict,
    *,
    force: bool = False,
) -> SyncResult:
    """Pull chat_request snapshots from Zeus into ~/.config/zeus_client/chat_requests/."""
    zcfg = resolve_zeus_config(cfg)
    zeus_url = (zcfg.get("url") or "").rstrip("/")
    if not zeus_url:
        raise RuntimeError("no Zeus URL configured")

    dest = user_chat_requests_dir()
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / _MANIFEST_NAME
    prior = _load_manifest(dest)
    prior_files = prior.get("files") if isinstance(prior.get("files"), dict) else {}

    scopes = resolve_sync_scopes(cfg, zcfg)
    if not scopes:
        raise RuntimeError("no scopes configured for chat_requests sync")

    result = SyncResult(manifest_path=manifest_path)
    next_files: dict[str, dict] = dict(prior_files)

    for bucket, scope in scopes:
        headers, auth_note = await resolve_zeus_auth(zeus_url, zcfg, bucket, scope)
        logger.info(f"sync_chat_requests: scope={bucket}/{scope} auth={auth_note}")
        modes = resolve_sync_modes(cfg, bucket, scope)
        scope_dir = dest / scope_chat_requests_subdir(bucket, scope)
        scope_dir.mkdir(parents=True, exist_ok=True)

        for mode in modes:
            key = _manifest_key(bucket, scope, mode)
            try:
                doc = await fetch_scope_chat_request(
                    zeus_url, bucket, scope, mode, headers,
                )
                filename = chat_request_filename(mode)
                out = scope_dir / filename
                doc_hash = _doc_fingerprint(doc)
                prev = prior_files.get(key) if isinstance(prior_files.get(key), dict) else {}

                if (
                    not force
                    and prev.get("hash") == doc_hash
                    and out.is_file()
                    and prev.get("path") == str(out.relative_to(dest))
                ):
                    result.skipped.append({
                        "scope": f"{bucket}/{scope}",
                        "mode": mode,
                        "path": str(out.relative_to(dest)),
                        "hash": doc_hash,
                    })
                    continue

                await asyncio.to_thread(_atomic_write_json, out, doc)
                rel = str(out.relative_to(dest))
                entry = {
                    "scope": f"{bucket}/{scope}",
                    "mode": mode,
                    "path": rel,
                    "hash": doc_hash,
                }
                result.synced.append(entry)
                next_files[key] = {
                    **entry,
                    "synced_at": time.time(),
                }
            except Exception as e:
                logger.warning(f"sync_chat_requests: failed {key}: {e}")
                result.errors.append({
                    "scope": f"{bucket}/{scope}",
                    "mode": mode,
                    "error": str(e),
                })

    manifest = {
        "version": _MANIFEST_VERSION,
        "synced_at": time.time(),
        "zeus_url": zeus_url,
        "files": next_files,
    }
    await asyncio.to_thread(_write_manifest, manifest_path, manifest)
    return result