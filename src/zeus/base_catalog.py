"""Load chat_request catalogs by base_id (base-5+ filename + lineage).

ZC-WISH-001: open ``chat_request_<mode>_base-<id>.json``; refuse lineage
mismatch; never invent production ``contract_hash`` / stamp values.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

_BASE_FILE_RE = re.compile(
    r"^chat_request_(?P<mode>.+)_base-(?P<base_rest>.+)\.json$"
)


def parse_catalog_filename(name: str) -> Optional[dict]:
    """Parse ``chat_request_<mode>_base-<N>.json`` → mode + base_id."""
    stem_name = Path(name).name
    m = _BASE_FILE_RE.match(stem_name)
    if not m:
        return None
    return {
        "mode": m.group("mode"),
        "base_id": f"base-{m.group('base_rest')}",
        "file": stem_name,
    }


def list_base_catalogs(search_dirs: Iterable[Path]) -> list[dict]:
    """Discover base-N catalog files under search dirs (rglob)."""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for d in search_dirs:
        root = Path(d)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("chat_request_*_base-*.json")):
            meta = parse_catalog_filename(p.name)
            if not meta:
                continue
            key = (meta["base_id"], meta["mode"], str(p.resolve()))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                **meta,
                "path": str(p),
                "origin": str(root),
            })
    return out


def find_base_catalog_path(
    *,
    base_id: str,
    mode: str,
    search_dirs: Iterable[Path],
) -> Optional[Path]:
    """Resolve path for ``chat_request_<mode>_<base_id>.json``."""
    want = f"chat_request_{mode}_{base_id}.json"
    for d in search_dirs:
        root = Path(d)
        if not root.is_dir():
            continue
        direct = root / want
        if direct.is_file():
            return direct
        # min/ layout: .../min/chat_request_...
        for p in root.rglob(want):
            if p.is_file():
                return p
    return None


def load_base_catalog(
    *,
    base_id: str,
    mode: str,
    search_dirs: Iterable[Path],
    require_lineage: bool = True,
) -> dict:
    """Load a base-N min catalog JSON.

    Raises:
        FileNotFoundError: no matching file
        ValueError: lineage base_id mismatch when present
    """
    if not base_id or not str(base_id).startswith("base-"):
        raise ValueError(f"base_id must look like 'base-N', got {base_id!r}")
    path = find_base_catalog_path(
        base_id=base_id, mode=mode, search_dirs=search_dirs,
    )
    if path is None:
        raise FileNotFoundError(
            f"no catalog chat_request_{mode}_{base_id}.json under {list(search_dirs)}"
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"catalog root must be object: {path}")

    lineage_raw = doc.get("_lineage")
    lineage: dict = lineage_raw if isinstance(lineage_raw, dict) else {}
    got = lineage.get("base_id")
    if got is not None and got != base_id:
        raise ValueError(
            f"lineage base_id {got!r} != requested {base_id!r} ({path.name})"
        )
    if require_lineage and got is None:
        raise ValueError(
            f"catalog missing _lineage.base_id (refusing silent load): {path.name}"
        )

    # Never invent stamp/hash — leave contract as shipped (often prototype).
    return doc
