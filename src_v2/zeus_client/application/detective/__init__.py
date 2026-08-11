"""Client Detective briefing projector (ZCM-005 / ZCM-007)."""

from __future__ import annotations

from zeus_client_v2.application.detective.build import (
    build_detective_briefing,
    detective_enabled,
    safe_build_detective_briefing,
)
from zeus_client_v2.application.detective.playbooks import PLAYBOOK_IDS

__all__ = [
    "build_detective_briefing",
    "safe_build_detective_briefing",
    "detective_enabled",
    "PLAYBOOK_IDS",
]
