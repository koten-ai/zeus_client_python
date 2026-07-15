"""Configure kotenai-zeus-client paths for this app's layout.

Recipe R01 — set env BEFORE any zeus_client import.
Aligned with demo_travel_sample/src/travel_planner/zeus_config.py.
"""
from __future__ import annotations

import os
from pathlib import Path

# Package at src/<package>/zeus_config.py → project root is parents[2]
# (package → src → project). Adjust if your layout differs.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def configure_zeus_client() -> None:
    """Set env vars before any zeus_client import (constants read env at import time)."""
    os.environ.setdefault("ZEUS_CLIENT_CONFIG_DIR", str(PROJECT_ROOT))
    os.environ.setdefault(
        "ZEUS_CHAT_REQUESTS_DIR",
        str(PROJECT_ROOT / "data" / "chat_requests"),
    )
    os.environ.setdefault("CHAT_LOG_PATH", str(PROJECT_ROOT / "data" / "chats.jsonl"))
