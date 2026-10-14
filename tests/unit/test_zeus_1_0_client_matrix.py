"""ZCP-124: the Zeus 1.0.0 row names an available package tag."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_zeus_1_0_row_names_the_available_tag() -> None:
    pins = json.loads((ROOT / "sdk_bootstrap.pins.json").read_text(encoding="utf-8"))
    row = pins["zeus_1_0_client"]
    version = "2.4.1"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{version}"' in pyproject
    assert row["package"] == "kotenai-zeus-client"
    assert row["available_tag"] == f"v{version}"
    assert row["matrix_ticket"] == "ZE-77"
    assert row["auth_modes_on_tag"] == ["basic", "bearer", "session"]
    assert "pat" in row["auth_modes_unreleased"]
    assert "m2m" in row["auth_modes_unreleased"]
    text = (ROOT / "docs/V2/ZEUS_1_0_CLIENT_MATRIX.md").read_text(encoding="utf-8")
    assert row["available_tag"] in text
    assert "ZCP-1" in text
    assert "In Review" in text
    assert "ZCP-123" in text
    assert "ZCP-122" in text
