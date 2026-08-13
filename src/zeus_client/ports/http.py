"""Optional low-level HTTP port."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

__all__ = ["HttpPort"]


@runtime_checkable
class HttpPort(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        timeout_s: float | None = None,
    ) -> tuple[int, Mapping[str, str], bytes]: ...

    async def aclose(self) -> None: ...
