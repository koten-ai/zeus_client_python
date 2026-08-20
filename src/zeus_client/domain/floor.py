"""Client floor vs catalog BASE wire (independent of package semver)."""

from __future__ import annotations

import logging
import re

from zeus_client.domain.errors import CatalogError, ErrorCode

logger = logging.getLogger("zeus_client.catalog")

__all__ = [
    "DEFAULT_CLIENT_FLOOR",
    "floor_rank",
    "floor_required_for_base_id",
    "assert_floor_allows",
]

DEFAULT_CLIENT_FLOOR = "client-floor-5"

_FLOOR_RANK = {
    "client-floor-1": 1,
    "client-floor-4": 4,
    "client-floor-5": 5,
    "client-floor-6": 6,
    "client-floor-6.1": 61,
}

_BASE_RE = re.compile(r"^base-(?P<maj>\d+)(?:\.(?P<min>\d+))?$")


def floor_rank(floor_id: str | None) -> int:
    key = (floor_id or DEFAULT_CLIENT_FLOOR).strip() or DEFAULT_CLIENT_FLOOR
    if key in _FLOOR_RANK:
        return _FLOOR_RANK[key]
    m = re.match(r"client-floor-(\d+)(?:\.(\d+))?", key)
    if not m:
        return _FLOOR_RANK[DEFAULT_CLIENT_FLOOR]
    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    return major * 10 + minor if minor else major


def floor_required_for_base_id(base_id: str | None) -> str:
    """Map pack ``base_id`` to the minimum client floor that may load it."""
    raw = (base_id or "").strip()
    if raw.startswith("cus-"):
        return DEFAULT_CLIENT_FLOOR
    m = _BASE_RE.match(raw)
    if not m:
        return DEFAULT_CLIENT_FLOOR
    major = int(m.group("maj"))
    minor = int(m.group("min") or 0)
    if major <= 1:
        return "client-floor-1"
    if major <= 4:
        return "client-floor-4"
    if major == 5:
        return "client-floor-5"
    if major == 6 and minor >= 1:
        return "client-floor-6.1"
    if major >= 6:
        return "client-floor-6"
    return DEFAULT_CLIENT_FLOOR


def assert_floor_allows(
    *,
    client_floor: str,
    base_id: str | None,
    allow_degraded: bool = False,
) -> None:
    """Fail closed when pack wire requires a higher floor than the client."""
    if not base_id:
        return
    need = floor_required_for_base_id(base_id)
    if floor_rank(client_floor) >= floor_rank(need):
        return
    msg = f"catalog base_id {base_id!r} requires {need}; client.floor is {client_floor!r}"
    if allow_degraded:
        logger.error("catalog.floor_degraded: %s", msg)
        return
    raise CatalogError(
        code=ErrorCode.PRECONDITION_FAILED,
        component="domain.floor",
        public_message=msg,
        details={
            "base_id": base_id,
            "required_floor": need,
            "client_floor": client_floor,
        },
    )
