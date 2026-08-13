"""Catalog domain — path resolution, brief merge, load shapes (pure).

Fail-closed path order (locked):
1. ``{user_dir}/{bucket}__{scope_tail}/chat_request_{mode}_v2.json``
2. ``{user_dir}/chat_request_{mode}_v2.json`` (top-level only — **no** sibling ``*__*`` rglob)
3. ``{bundled_dir}/chat_request_{mode}_v2.json``
4. else missing (caller raises ``CatalogError``)

Never invent production stamps.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from zeus_client.domain.contract import (
    extract_stamped_hash,
    heal_trailing_ws_stamp_drift,
)

__all__ = [
    "MANIFEST_NAME",
    "LoadedCatalog",
    "scope_chat_requests_subdir",
    "scope_key_from_subdir",
    "chat_request_filename",
    "mode_from_filename",
    "resolve_catalog_path",
    "extract_scope_brief",
    "merge_scope_brief",
    "normalize_chat_request_shape",
    "prepare_loaded_document",
    "list_catalog_entries",
]

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class LoadedCatalog:
    """Catalog body after load + heal (optional brief merge is caller's job)."""

    body: Mapping[str, Any]
    path: str | None
    source: str
    contract_hash: str | None = None


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


def chat_request_filename(mode: str) -> str:
    """On-disk filename for a mode (default → chat_request_v2.json)."""
    m = (mode or "default").strip() or "default"
    if m == "default":
        return "chat_request_v2.json"
    return f"chat_request_{m}_v2.json"


def mode_from_filename(name: str) -> str:
    stem = Path(name).stem
    if stem in ("chat_request", "chat_request_v2"):
        return "default"
    if stem.startswith("chat_request_"):
        mode = stem[len("chat_request_") :]
        if mode.endswith("_v2"):
            mode = mode[:-3]
        return mode
    return stem


def resolve_catalog_path(
    *,
    mode: str,
    bucket: str | None,
    scope: str | None,
    user_dir: Path,
    bundled_dir: Path | None = None,
) -> Path | None:
    """Resolve catalog path without sibling-scope rglob.

    Returns the first existing file in locked order, or ``None``.
    """
    filename = chat_request_filename(mode)
    candidates: list[Path] = []

    if bucket and scope:
        candidates.append(user_dir / scope_chat_requests_subdir(bucket, scope) / filename)

    # User general: **direct children of user_dir only** — never rglob into *__* siblings.
    candidates.append(user_dir / filename)

    if bundled_dir is not None:
        candidates.append(Path(bundled_dir) / filename)

    for p in candidates:
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


def list_catalog_entries(
    user_dir: Path,
    bundled_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Discover catalogs under user + bundled roots (no duplicate file/mode)."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add_from(root: Path, origin: str) -> None:
        if not root.is_dir():
            return
        # Top-level general files
        for p in sorted(root.glob("*.json")):
            if p.name == MANIFEST_NAME:
                continue
            mode = mode_from_filename(p.name)
            key = (p.name, mode)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "mode": mode,
                    "file": p.name,
                    "source": "general",
                    "origin": origin,
                    "path": str(p),
                }
            )
        # Scope subdirs
        for sub in sorted(x for x in root.iterdir() if x.is_dir()):
            src = scope_key_from_subdir(sub.name) or sub.name
            for p in sorted(sub.glob("*.json")):
                if p.name == MANIFEST_NAME:
                    continue
                rel = f"{sub.name}/{p.name}"
                mode = mode_from_filename(p.name)
                key = (rel, mode)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "mode": mode,
                        "file": rel,
                        "source": src,
                        "origin": origin,
                        "path": str(p),
                    }
                )

    _add_from(user_dir, "synced")
    if bundled_dir is not None:
        _add_from(Path(bundled_dir), "bundled")
    return out
