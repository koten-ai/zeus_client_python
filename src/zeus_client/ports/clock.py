"""Default system clock implementation."""

from __future__ import annotations

import time
from typing import Protocol

__all__ = ["Clock", "SystemClock"]


class Clock(Protocol):
    def now_ms(self) -> int: ...

    def monotonic_ms(self) -> int: ...


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)
