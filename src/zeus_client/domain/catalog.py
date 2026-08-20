"""Catalog domain — path resolution, brief merge, load shapes (pure).

Fail-closed path order (locked):
1. ``{user_dir}/{bucket}__{scope_tail}/`` then listing-inverse filenames
2. ``{user_dir}/`` (top-level only — **no** sibling ``*__*`` rglob)
3. ``{bundled_dir}/``
4. else missing (caller raises ``CatalogError``)

At each location, names are the inverse of ``mode_from_filename``:
canonical ``chat_request_{mode}_v2.json`` first, then
``chat_request_{mode}.json``, then stem ``{mode}.json``. Writes still use
``chat_request_filename``.

Never invent production stamps.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zeus_client.domain.contract import (
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
)
from zeus_client.domain.errors import CatalogError, ErrorCode

__all__ = [
    "MANIFEST_NAME",
    "LoadedCatalog",
    "scope_chat_requests_subdir",
    "scope_key_from_subdir",
    "chat_request_filename",
    "catalog_filenames_for_mode",
    "mode_from_filename",
    "parse_catalog_filename",
    "lineage_base_id",
    "check_lineage",
    "resolve_catalog_path",
    "extract_scope_brief",
    "merge_scope_brief",
    "normalize_chat_request_shape",
    "prepare_loaded_document",
    "list_catalog_entries",
    "catalog_entry_stats",
]

_LINEAGE_FILE_RE = re.compile(r"^chat_request_(?P<mode>.+)_(?P<base_id>(?:base|cus)-.+)\.json$")

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class LoadedCatalog:
    """Catalog body after load + heal (optional brief merge is caller's job)."""

    body: Mapping[str, Any]
    path: str | None
    source: str
    contract_hash: str | None = None
    base_id: str | None = None
    lineage_id: str | None = None
    response_output_schema: Mapping[str, Any] | None = None
    response_output_example: Mapping[str, Any] | None = None


def scope_chat_requests_subdir(bucket: str, scope: str) -> str:
    """Filesystem-safe dir for a bucket/scope (beer-sample/_default → beer-sample__default)."""
    tail = scope[1:] if scope.startswith("_") else scope
    return f"{bucket}__{tail}"


def scope_key_from_subdir(name: str) -> str | None:
    if "__" not in name:
        return None
    bucket, tail = name.split("__", 1)
    scope = f"_{tail}" if tail else tail
    return f"{bucket}/{scope}"


def chat_request_filename(mode: str, base_id: str | None = None) -> str:
    """On-disk filename for a mode (default → chat_request_v2.json)."""
    m = (mode or "default").strip() or "default"
    bid = (base_id or "").strip()
    if bid:
        return f"chat_request_{m}_{bid}.json"
    if m == "default":
        return "chat_request_v2.json"
    return f"chat_request_{m}_v2.json"


def _is_single_path_component(name: str | None) -> bool:
    if not name:
        return False
    parts = Path(name).parts
    return len(parts) == 1 and parts[0] not in (".", "..")


def catalog_filenames_for_mode(mode: str, base_id: str | None = None) -> list[str]:
    """Filenames that ``mode_from_filename`` would map back to this mode."""
    bid = (base_id or "").strip()
    if bid:
        return [chat_request_filename(mode, bid)]
    m = (mode or "default").strip() or "default"
    if m == "default":
        return ["chat_request_v2.json", "chat_request.json"]
    if not _is_single_path_component(m) or ".." in m:
        return []
    names = [
        f"chat_request_{m}_v2.json",
        f"chat_request_{m}.json",
        f"{m}.json",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def parse_catalog_filename(name: str) -> dict[str, str] | None:
    """Parse ``chat_request_<mode>_<base-N|cus-*>.json`` → mode + base_id."""
    stem_name = Path(name).name
    m = _LINEAGE_FILE_RE.match(stem_name)
    if not m:
        return None
    return {
        "mode": m.group("mode"),
        "base_id": m.group("base_id"),
        "file": stem_name,
    }


def mode_from_filename(name: str) -> str:
    parsed = parse_catalog_filename(name)
    if parsed:
        return parsed["mode"]
    stem = Path(name).stem
    if stem in ("chat_request", "chat_request_v2"):
        return "default"
    if stem.startswith("chat_request_"):
        mode = stem[len("chat_request_") :]
        if mode.endswith("_v2"):
            mode = mode[:-3]
        return mode
    return stem


def lineage_base_id(doc: Mapping[str, Any] | None) -> str | None:
    """``_lineage.base_id`` when present and non-empty."""
    if not isinstance(doc, Mapping):
        return None
    raw = doc.get("_lineage")
    if not isinstance(raw, Mapping):
        return None
    got = raw.get("base_id")
    if isinstance(got, str) and got.strip():
        return got.strip()
    return None


def check_lineage(
    doc: Mapping[str, Any],
    base_id: str,
    *,
    require_lineage: bool = True,
    path_name: str = "",
) -> None:
    """Refuse silent lineage mismatch. Never invent stamps."""
    want = (base_id or "").strip()
    if not want:
        return
    if not (want.startswith("base-") or want.startswith("cus-")):
        raise CatalogError(
            code=ErrorCode.CATALOG_LINEAGE_UNKNOWN,
            component="domain.catalog",
            public_message=f"base_id must look like 'base-N' or 'cus-*', got {base_id!r}",
            details={"base_id": base_id},
        )
    got = lineage_base_id(doc)
    label = path_name or "catalog"
    if got is not None and got != want:
        raise CatalogError(
            code=ErrorCode.CATALOG_LINEAGE_UNKNOWN,
            component="domain.catalog",
            public_message=f"lineage base_id {got!r} != requested {want!r} ({label})",
            details={"requested": want, "got": got, "path": path_name},
        )
    if require_lineage and got is None:
        raise CatalogError(
            code=ErrorCode.CATALOG_LINEAGE_UNKNOWN,
            component="domain.catalog",
            public_message=f"catalog missing _lineage.base_id (refusing silent load): {label}",
            details={"requested": want, "path": path_name},
        )


def resolve_catalog_path(
    *,
    mode: str,
    bucket: str | None,
    scope: str | None,
    user_dir: Path,
    bundled_dir: Path | None = None,
    base_id: str | None = None,
) -> Path | None:
    """Resolve catalog path without sibling-scope rglob.

    Returns the first existing file in locked order, or ``None``.
    At each location, try listing-inverse filenames (canonical first).
    """
    names = catalog_filenames_for_mode(mode, base_id)
    if not names:
        return None

    locations: list[Path] = []
    if bucket and scope:
        scope_dir = user_dir / scope_chat_requests_subdir(bucket, scope)
        locations.append(scope_dir)
        locations.append(scope_dir / "min")

    # User general: **direct children of user_dir only** — never rglob into *__* siblings.
    locations.append(user_dir)
    locations.append(user_dir / "min")

    if bundled_dir is not None:
        b = Path(bundled_dir)
        locations.append(b)
        locations.append(b / "min")

    for loc in locations:
        for name in names:
            p = loc / name
            try:
                if p.is_file():
                    return p
            except OSError:
                continue
    return None


def extract_scope_brief(chat_req: Mapping[str, Any] | dict) -> str:
    """Pull the live ## SCOPE BRIEF suffix from messages or instructions."""
    try:
        content = (chat_req.get("messages") or [{}])[0].get("content") or ""
        marker = "## SCOPE BRIEF"
        idx = content.find(marker)
        if idx >= 0:
            return content[idx:].strip()
        instr = chat_req.get("instructions") or {}
        if isinstance(instr, dict):
            sp = instr.get("system_prompt") or ""
            idx = sp.find(marker)
            if idx >= 0:
                return sp[idx:].strip()
    except Exception:
        pass
    return ""


def merge_scope_brief(chat_req: dict, brief: str) -> dict:
    """Append a live scope brief to system surfaces (hash-safe after strip markers)."""
    if not brief:
        return chat_req
    out = deepcopy(chat_req)
    messages = out.get("messages") or []
    if messages:
        current = messages[0].get("content") or ""
        if "## SCOPE BRIEF" not in current and "## MINI-SCHEMA" not in current:
            messages[0]["content"] = current.rstrip(" \t\n\r") + "\n\n" + brief.strip()
    instr = out.get("instructions") or {}
    if isinstance(instr, dict):
        sp = instr.get("system_prompt") or ""
        if sp and "## SCOPE BRIEF" not in sp and "## MINI-SCHEMA" not in sp:
            instr["system_prompt"] = sp.rstrip(" \t\n\r") + "\n\n" + brief.strip()
            out["instructions"] = instr
    return out


def normalize_chat_request_shape(doc: Any) -> dict:
    """Light normalize: ensure dict; leave structure otherwise intact."""
    if not isinstance(doc, dict):
        return {}
    return doc


def path_source_label(path: Path, *, user_dir: Path, bundled_dir: Path | None) -> str:
    """Human-readable origin for logs / LoadedCatalog.source."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        user_r = user_dir.resolve()
    except OSError:
        user_r = user_dir
    try:
        rel = resolved.relative_to(user_r)
        parts = rel.parts
        if len(parts) >= 2 and "__" in parts[0]:
            return f"synced ({rel.as_posix()})"
        return f"user_general ({rel.as_posix()})"
    except ValueError:
        pass
    if bundled_dir is not None:
        try:
            rel_b = resolved.relative_to(Path(bundled_dir).resolve())
            return f"bundled ({rel_b.as_posix()})"
        except (ValueError, OSError):
            pass
    return f"file ({path.name})"


def prepare_loaded_document(raw: dict) -> dict:
    """Normalize + heal trailing-ws stamp drift (never forges stamps)."""
    doc = normalize_chat_request_shape(raw)
    return heal_trailing_ws_stamp_drift(doc)


def catalog_entry_stats(path: Path, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Light list/info stats. Never invents a production stamp."""
    parsed = parse_catalog_filename(path.name)
    doc = body
    if doc is None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            doc = raw if isinstance(raw, dict) else None
        except (OSError, json.JSONDecodeError):
            doc = None
    verbs = []
    if isinstance(doc, Mapping):
        raw_v = doc.get("verbs")
        if not isinstance(raw_v, list):
            raw_v = doc.get("tools")
        if isinstance(raw_v, list):
            verbs = raw_v
    stamped = extract_stamped_hash(dict(doc)) if isinstance(doc, Mapping) else ""
    lineage = lineage_base_id(doc) if isinstance(doc, Mapping) else None
    base_id = (parsed or {}).get("base_id") or lineage
    return {
        "base_id": base_id or "",
        "lineage_id": lineage or "",
        "stamp_present": "true" if stamped else "false",
        "verb_count": str(len(verbs)),
        "contract_id": (
            str((doc.get("contract") or {}).get("id") or "")
            if isinstance(doc, Mapping) and isinstance(doc.get("contract"), Mapping)
            else ""
        ),
    }


def list_catalog_entries(
    user_dir: Path,
    bundled_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Discover catalogs under user + bundled roots (no duplicate file/mode)."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(path: Path, *, file: str, source: str, origin: str) -> None:
        if path.name == MANIFEST_NAME:
            return
        mode = mode_from_filename(path.name)
        key = (file, mode)
        if key in seen:
            return
        seen.add(key)
        stats = catalog_entry_stats(path)
        out.append(
            {
                "mode": mode,
                "file": file,
                "source": source,
                "origin": origin,
                "path": str(path),
                "base_id": stats["base_id"],
                "lineage_id": stats["lineage_id"],
                "stamp_present": stats["stamp_present"],
                "verb_count": stats["verb_count"],
            }
        )

    def _add_from(root: Path, origin: str) -> None:
        if not root.is_dir():
            return
        for p in sorted(root.glob("*.json")):
            _add(p, file=p.name, source="general", origin=origin)
        min_dir = root / "min"
        if min_dir.is_dir():
            for p in sorted(min_dir.glob("*.json")):
                _add(p, file=f"min/{p.name}", source="general", origin=origin)
        for sub in sorted(x for x in root.iterdir() if x.is_dir()):
            src = scope_key_from_subdir(sub.name) or sub.name
            for p in sorted(sub.glob("*.json")):
                _add(p, file=f"{sub.name}/{p.name}", source=src, origin=origin)
            nested_min = sub / "min"
            if nested_min.is_dir():
                for p in sorted(nested_min.glob("*.json")):
                    _add(
                        p,
                        file=f"{sub.name}/min/{p.name}",
                        source=src,
                        origin=origin,
                    )

    _add_from(user_dir, "synced")
    if bundled_dir is not None:
        _add_from(Path(bundled_dir), "bundled")
    return out
