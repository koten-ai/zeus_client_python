"""Paths + JSON helpers for the design-repo conformance suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "REPO_ROOT",
    "resolve_design_root",
    "load_json",
    "load_pins",
    "load_manifest",
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_pins() -> dict[str, Any]:
    p = REPO_ROOT / "sdk_bootstrap.pins.json"
    if p.exists():
        return load_json(p)
    return {}


def resolve_design_root(pins: dict[str, Any] | None = None) -> Path:
    pins = pins or load_pins()
    ref = (pins.get("suite") or {}).get("design_repo_ref") or "local:../zeus_client_design"
    if ref.startswith("local:"):
        rel = ref.split(":", 1)[1]
        path = (REPO_ROOT / rel).resolve()
    else:
        path = Path(ref).resolve()
    if not path.is_dir():
        # fallback sibling
        alt = (REPO_ROOT.parent / "zeus_client_design").resolve()
        if alt.is_dir():
            return alt
        raise FileNotFoundError(f"design repo not found: {path}")
    return path


def load_manifest(design_root: Path) -> dict[str, Any]:
    return load_json(design_root / "conformance" / "manifest.json")
