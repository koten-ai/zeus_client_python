"""Product report/session root stamps (CHECKLIST D · ZC-WISH-035).

Product SDK always writes ``user=zeus_client``. Hub/admin is a different
surface (``admin``) and must never be claimed here. ``ip_address`` is
optional: omit when unknown; never invent.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from zeus_client._version import __version__ as PACKAGE_VERSION

__all__ = [
    "PRODUCT_USER",
    "PRODUCT_USER_ENUM",
    "is_ip_text",
    "is_loopback_ip",
    "resolve_client_ip",
    "product_stamp",
    "assert_product_stamp",
    "best_effort_host_ip",
]

PRODUCT_USER = "zeus_client"
PRODUCT_USER_ENUM = frozenset({"zeus_client", "zeus", "helios", "admin"})
_IP_ENV = "ZEUS_CLIENT_IP"


def is_ip_text(value: str | None) -> bool:
    """True when ``value`` is a textual IPv4 or IPv6 address."""
    text = str(value or "").strip()
    if not text:
        return False
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def is_loopback_ip(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return bool(ipaddress.ip_address(text).is_loopback)
    except ValueError:
        return False


def best_effort_host_ip() -> str | None:
    """Non-loopback host IP when the OS can resolve one; else None."""
    for family, probe in ((socket.AF_INET, "8.8.8.8"), (socket.AF_INET6, "2001:4860:4860::8888")):
        sock = None
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.connect((probe, 80))
            raw = sock.getsockname()[0]
            ip = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
            if is_ip_text(ip) and not is_loopback_ip(ip):
                return ip
        except OSError:
            continue
        finally:
            if sock is not None:
                sock.close()
    return None


def resolve_client_ip(
    config_ip: str | None = None,
    env: Mapping[str, str] | None = None,
    *,
    probe_host: bool = True,
) -> str | None:
    """Config/env override, then optional non-loopback host IP.

    Configured or env values may be loopback (operator-explicit). Best-effort
    probe never returns loopback.
    """
    for raw in (config_ip, (env or os.environ).get(_IP_ENV)):
        text = str(raw or "").strip()
        if is_ip_text(text):
            return text
    if probe_host:
        return best_effort_host_ip()
    return None


def product_stamp(
    *,
    ip_address: str | None = None,
    version: str | None = None,
    ts: str | None = None,
    scope: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Root identity for session/report sinks. Product ``user`` is fixed."""
    out: dict[str, Any] = {
        "user": PRODUCT_USER,
        "version": version or PACKAGE_VERSION,
    }
    ip = str(ip_address or "").strip()
    if is_ip_text(ip):
        out["ip_address"] = ip
    if ts:
        out["ts"] = str(ts)
    else:
        out["ts"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if scope:
        out["scope"] = str(scope)
    if session_id:
        out["session_id"] = str(session_id)
    return out


def assert_product_stamp(stamp: Mapping[str, Any]) -> None:
    """Test/audit helper — product sinks must never claim Hub admin traffic."""
    user = str(stamp.get("user") or "")
    if user != PRODUCT_USER:
        raise AssertionError(f"product stamp user must be {PRODUCT_USER!r}, got {user!r}")
    if user == "admin":
        raise AssertionError("product SDK must not stamp user=admin")
    ip = stamp.get("ip_address")
    if ip is not None and not is_ip_text(str(ip)):
        raise AssertionError(f"ip_address must be omitted or a real IP, got {ip!r}")
