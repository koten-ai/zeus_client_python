"""ZeusRuntime entrypoint (Phase 2 wires ports; Phase 0 stub only)."""

from __future__ import annotations


class ZeusRuntime:
    """Async context-managed runtime — implemented in Phase 2 (ZCP-8)."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "ZeusRuntime.from_config is implemented in Phase 2; Phase 0 is import scaffold only."
        )

    @classmethod
    def from_config(cls, *args: object, **kwargs: object) -> ZeusRuntime:
        raise NotImplementedError(
            "ZeusRuntime.from_config is implemented in Phase 2; Phase 0 is import scaffold only."
        )


__all__ = ["ZeusRuntime"]
