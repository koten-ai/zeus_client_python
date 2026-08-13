"""Tests for python3/zeus/proxy_auth.py."""
import pytest

from zeus_client.zeus.proxy_auth import (
    basic_auth_for_login,
    format_auth_failure,
    is_nginx_proxy_rejection,
    proxy_auth_tuple,
    validate_zeus_engine_url,
)


def test_proxy_auth_tuple_nested():
    zcfg = {"proxy_auth": {"username": "nginx_user", "password": "nginx_pass"}}
    assert proxy_auth_tuple(zcfg) == ("nginx_user", "nginx_pass")


def test_proxy_auth_tuple_flat_fields():
    zcfg = {"proxy_auth_username": "u", "proxy_auth_password": "p"}
    assert proxy_auth_tuple(zcfg) == ("u", "p")


def test_proxy_auth_tuple_missing():
    assert proxy_auth_tuple({}) is None
    assert proxy_auth_tuple({"proxy_auth": {"username": "only"}}) is None


def test_validate_zeus_engine_url_rejects_client_port():
    err = validate_zeus_engine_url("http://165.232.164.75:9999")
    assert err is not None
    assert "9999" in err
    assert "8080" in err


def test_validate_zeus_engine_url_accepts_engine_port():
    assert validate_zeus_engine_url("http://zeus.example:8080") is None


def test_is_nginx_proxy_rejection_html_body():
    body = "<html><head><title>401 Authorization Required</title></head><body><center>nginx/1.31.1</center></body></html>"
    assert is_nginx_proxy_rejection(401, body) is True


def test_is_nginx_proxy_rejection_zeus_json():
    assert is_nginx_proxy_rejection(401, '{"error":"unauthorized"}') is False


def test_format_auth_failure_client_url():
    msg = format_auth_failure("http://host:9999", 401, "<html>nginx</html>")
    assert "Zeus Client" in msg or "9999" in msg


def test_format_auth_failure_nginx_behind_engine():
    body = "<html><head><title>401 Authorization Required</title></head></html>"
    msg = format_auth_failure(
        "http://zeus:8080", 401, body,
        response_headers={"WWW-Authenticate": 'Basic realm="Zeus API"', "Server": "nginx/1.31.1"},
    )
    assert "nginx reverse proxy" in msg
    assert "proxy_auth" in msg


def test_basic_auth_for_login_without_proxy():
    assert basic_auth_for_login({}, "zeus", "secret") == ("zeus", "secret")


def test_basic_auth_for_login_matching_proxy():
    zcfg = {"proxy_auth": {"username": "same", "password": "pw"}}
    assert basic_auth_for_login(zcfg, "same", "pw") == ("same", "pw")


def test_basic_auth_for_login_conflicting_proxy_raises():
    zcfg = {"proxy_auth": {"username": "nginx", "password": "nginx-pw"}}
    with pytest.raises(RuntimeError, match="proxy_auth credentials differ"):
        basic_auth_for_login(zcfg, "zeus", "zeus-pw")