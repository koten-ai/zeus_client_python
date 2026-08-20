"""Product root stamps (CHECKLIST D · ZC-WISH-035)."""

from __future__ import annotations

import pytest

from zeus_client.domain.stamps import (
    PRODUCT_USER,
    assert_product_stamp,
    is_ip_text,
    product_stamp,
    resolve_client_ip,
)


def test_product_stamp_user_and_version() -> None:
    s = product_stamp()
    assert s["user"] == PRODUCT_USER
    assert s["version"]
    assert "ip_address" not in s
    assert_product_stamp(s)


def test_product_stamp_includes_valid_ip() -> None:
    s = product_stamp(ip_address="203.0.113.42")
    assert s["ip_address"] == "203.0.113.42"


def test_product_stamp_omits_invalid_ip() -> None:
    s = product_stamp(ip_address="not-an-ip")
    assert "ip_address" not in s
    s2 = product_stamp(ip_address="unknown")
    assert "ip_address" not in s2


def test_product_stamp_never_admin() -> None:
    s = product_stamp()
    assert s["user"] != "admin"
    with pytest.raises(AssertionError):
        assert_product_stamp({"user": "admin", "version": "1"})


def test_resolve_client_ip_config_allows_loopback() -> None:
    assert resolve_client_ip("127.0.0.1", env={}, probe_host=False) == "127.0.0.1"


def test_resolve_client_ip_env() -> None:
    assert (
        resolve_client_ip(None, env={"ZEUS_CLIENT_IP": "2001:db8::1"}, probe_host=False)
        == "2001:db8::1"
    )


def test_resolve_client_ip_omit_when_unknown() -> None:
    assert resolve_client_ip("  ", env={}, probe_host=False) is None


def test_is_ip_text() -> None:
    assert is_ip_text("192.0.2.1")
    assert is_ip_text("::1")
    assert not is_ip_text("")
    assert not is_ip_text("localhost")
