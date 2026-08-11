"""Plugin registration stub (out of alpha claim; hooks reserved)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["PluginRegistry"]


@dataclass
class PluginRegistry:
    """No-op plugin registry — multi-agent/plugins claim stays ``no`` until Phase 8+."""

    plugins: list[Any] = field(default_factory=list)

    def register(self, plugin: Any) -> None:
        self.plugins.append(plugin)
