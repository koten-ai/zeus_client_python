"""Clock port — wall and monotonic time in milliseconds."""

from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...

    def monotonic_ms(self) -> int: ...


__all__ = ["Clock"]
