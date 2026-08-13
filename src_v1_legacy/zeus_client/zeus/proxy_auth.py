"""Helpers for nginx / reverse-proxy HTTP Basic auth in front of Zeus."""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Typical Zeus Python client port (nginx sidecar); Zeus Engine API is usually :8080.
_ZEUS_CLIENT_PORTS = frozenset({8091, 9999})

_NGINX_HTML_MARKERS = (
    "<title>401 Authorization Required</title>",
    "<center>nginx/",
    "nginx/1.",
)


def proxy_auth_tuple(zcfg: dict | None) -> tuple[str, str] | None:
    """Return (username, password) for an nginx/proxy Basic gate, if configured."""
    if not zcfg:
        return None
    nested = zcfg.get("proxy_auth") or {}
    user = (nested.get("username") or zcfg.get("proxy_auth_username") or "").strip()
    pwd = nested.get("password") if nested.get("password") is not None else zcfg.get("proxy_auth_password")
    pwd = pwd if pwd is not None else ""
    if user and pwd != "":
        return user, pwd
    return None


def validate_zeus_engine_url(zeus_url: str) -> str | None:
    """Return a user-facing error when the URL clearly targets Zeus Client, not Engine."""
    parsed = urlparse((zeus_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if port in _ZEUS_CLIENT_PORTS:
        return (
            f"The URL {zeus_url} looks like a Zeus Client address (port {port}), "
            f"not the Zeus Engine API. Use the Zeus Engine public API URL "
            f"(typically port 8080, e.g. http://<host>:8080). "
            f"Port {port} is the Python client UI behind nginx and does not "
            f"expose /v1/.../auth/session."
        )
    return None


def is_nginx_proxy_rejection(status_code: int, body: str, headers: dict | None = None) -> bool:
    """True when the response looks like nginx auth_basic, not a Zeus JSON error."""
    if status_code != 401:
        return False
    text = body or ""
    if any(marker in text for marker in _NGINX_HTML_MARKERS):
        return True
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    www = hdrs.get("www-authenticate", "")
    server = hdrs.get("server", "")
    if "nginx" in server.lower() and "basic" in www.lower():
        return True
    return False


def _realm_from_www_authenticate(www_authenticate: str) -> str:
    m = re.search(r'realm="([^"]*)"', www_authenticate or "", re.I)
    return m.group(1) if m else ""


def format_auth_failure(
    zeus_url: str,
    status_code: int,
    body: str,
    *,
    response_headers: dict | None = None,
) -> str:
    """Build a helpful RuntimeError message for failed Zeus/proxy authentication."""
    hdrs = {k.lower(): v for k, v in (response_headers or {}).items()}
    www = hdrs.get("www-authenticate", "")

    url_err = validate_zeus_engine_url(zeus_url)
    if url_err:
        return url_err

    if is_nginx_proxy_rejection(status_code, body, hdrs):
        realm = _realm_from_www_authenticate(www)
        realm_note = f' (realm "{realm}")' if realm else ""
        return (
            f"HTTP {status_code} from an nginx reverse proxy{realm_note}, not from Zeus. "
            f"The proxy rejected the request before it reached the Zeus Engine. "
            f"If nginx requires its own credentials, add them under Proxy auth "
            f"in the connection settings (proxy_auth username/password). "
            f"When both nginx and Zeus need different Basic credentials, only one "
            f"Authorization header can be sent — use the same user in nginx htpasswd "
            f"and zeus_users, or configure nginx to skip auth_basic on "
            f"/readyz and /v1/*/auth/session."
        )

    snippet = (body or "").strip()[:300]
    return f"Zeus login failed ({status_code}): {snippet}"


def basic_auth_for_login(zcfg: dict, zeus_user: str, zeus_pwd: str) -> tuple[str, str]:
    """Pick httpx ``auth=`` credentials for a scoped Basic login POST.

    When proxy_auth is configured it must match the Zeus scope credentials
    (both layers share the single Authorization: Basic header).
    """
    proxy = proxy_auth_tuple(zcfg)
    zeus_pair = (zeus_user, zeus_pwd)
    if proxy:
        if proxy != zeus_pair:
            raise RuntimeError(
                "proxy_auth credentials differ from Zeus username/password. "
                "An nginx reverse proxy and Zeus both authenticate via the same "
                "Authorization: Basic header — only one username/password can be sent. "
                "Use identical credentials in nginx htpasswd and zeus_users, or "
                "configure nginx to skip auth_basic on /v1/*/auth/session and /readyz."
            )
        return proxy
    return zeus_pair