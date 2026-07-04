"""Zeus session cache and auth resolution."""
import asyncio
import time

import httpx

from zeus_client.constants import AUTH_TIMEOUT
from zeus_client.http_client import client
from zeus_client.logging_setup import logger
from zeus_client.zeus.proxy_auth import (
    basic_auth_for_login,
    format_auth_failure,
    proxy_auth_tuple,
    validate_zeus_engine_url,
)

_SESSION_CACHE: dict = {}   # key → {"sid", "pwd", "idle_ttl", "hard_deadline", "last_used"}
_SESSION_LOCK = asyncio.Lock()
# Re-mint this many seconds before the sliding idle window lapses so a
# session can never expire server-side between our check and the request.
_SESSION_IDLE_MARGIN_S = 30

async def invalidate_zeus_session(zeus_url, bucket, scope, user):
    """Drop a cached basic→session sid so the next resolve re-mints.
    Called when Zeus rejects a reused session (401)."""
    async with _SESSION_LOCK:
        _SESSION_CACHE.pop((zeus_url, bucket, scope, user), None)


async def resolve_zeus_auth(zeus_url, zcfg, bucket=None, scope=None, force=False):
    """Turn config's zeus.auth_mode into request headers for Zeus.
    Returns (headers, note). Raises RuntimeError on a failed login.

    NOTE: basic (username/password) login is now per-scope — Zeus
    authenticates the credential against `<bucket>.<scope>.zeus_users`,
    so the login must POST to /v1/{bucket}/{scope}/auth/session, not the
    old global /v1/auth/session (which now 401s for Basic). Because a
    user exists in exactly one scope, credentials are resolved per
    scope: `zeus.scope_credentials["<bucket>/<scope>"]` wins, otherwise
    the global `zeus.username`/`zeus.password` is used as a default.

    basic mode caches the minted session id and reuses it across turns
    (and across chats) so the expensive bcrypt login runs only once per
    session lifetime rather than on every request. Pass force=True to
    bypass the cache and re-mint (used by the 401 self-heal)."""
    zeus_url = (zeus_url or "").rstrip("/")
    url_err = validate_zeus_engine_url(zeus_url)
    if url_err:
        raise RuntimeError(url_err)

    mode = zcfg.get("auth_mode", "none")
    logger.debug(f"resolve_zeus_auth called: mode={mode}, bucket={bucket}, scope={scope}, force={force}")
    if mode == "none":
        logger.debug("auth mode=none (dev_no_auth)")
        return {}, "no auth (dev_no_auth)"
    if mode == "bearer":
        tok = (zcfg.get("bearer_token") or "").strip()
        if not tok:
            raise RuntimeError("bearer mode selected but bearer_token is empty")
        return {"Authorization": f"Bearer {tok}"}, "bearer token"
    if mode == "session":
        sid = (zcfg.get("session_id") or "").strip()
        if not sid:
            raise RuntimeError("session mode selected but session_id is empty")
        return {"X-Zeus-Session": sid}, "session id"
    if mode == "basic":
        if not bucket or not scope:
            logger.warning("basic auth requested but no bucket/scope provided — this will fail for per-scope logins")
            raise RuntimeError(
                "basic mode needs a bucket+scope: Zeus username/password "
                "login is per-scope (POST /v1/{bucket}/{scope}/auth/session)")
        # Credentials are per-scope (a user lives in exactly one scope's
        # zeus_users). Prefer a scope-specific entry keyed by
        # "<bucket>/<scope>"; fall back to the global zeus.username/password
        # (handy when the same admin was bootstrapped into every scope).
        scope_creds = (zcfg.get("scope_credentials") or {}).get(f"{bucket}/{scope}") or {}
        user = scope_creds.get("username") or zcfg.get("username") or ""
        pwd = scope_creds.get("password") or zcfg.get("password") or ""
        if not user:
            logger.error(f"no credentials found for scope {bucket}/{scope}")
            raise RuntimeError(
                f"no credentials for scope {bucket}/{scope}: add them under "
                f"zeus.scope_credentials['{bucket}/{scope}'] or zeus.username/password")

        cache_key = (zeus_url, bucket, scope, user)
        now = time.time()
        # Fast path: reuse a cached session that is comfortably within
        # both the sliding idle window and the absolute hard TTL. Every
        # authenticated request we make refreshes the idle window on
        # Zeus, so last_used is the right clock to compare against.
        if not force:
            async with _SESSION_LOCK:
                ent = _SESSION_CACHE.get(cache_key)
                if (ent and ent.get("pwd") == pwd
                        and now < ent["hard_deadline"]
                        and (now - ent["last_used"]) < (ent["idle_ttl"] - _SESSION_IDLE_MARGIN_S)):
                    ent["last_used"] = now
                    sid = ent["sid"]
                    return ({"X-Zeus-Session": sid},
                            f"basic→session {bucket}/{scope} {sid[:14]}… (cached)")

        login_auth = basic_auth_for_login(zcfg, user, pwd)
        logger.debug(f"performing basic login for {zeus_url}/v1/{bucket}/{scope}/auth/session user={user}")
        try:
            r = await client().post(
                f"{zeus_url}/v1/{bucket}/{scope}/auth/session",
                auth=login_auth, timeout=AUTH_TIMEOUT)
        except httpx.HTTPError as e:
            err = str(e).strip() or type(e).__name__
            logger.warning(
                f"Zeus basic login unreachable for {bucket}/{scope} url={zeus_url}: {err}")
            raise RuntimeError(f"Zeus unreachable at {zeus_url}: {err}") from e
        if r.status_code != 200:
            logger.error(f"Zeus basic login failed for {bucket}/{scope}: {r.status_code} {r.text[:300]}")
            raise RuntimeError(format_auth_failure(
                zeus_url, r.status_code, r.text,
                response_headers=dict(r.headers),
            ))
        body = r.json()
        sid = body.get("session_id", "")
        if not sid:
            logger.error("Zeus login returned no session_id")
            raise RuntimeError("Zeus login returned no session_id")
        logger.info(f"basic session obtained for {bucket}/{scope} sid={sid[:12]}… (cached for future calls)")
        # expires_in = sliding idle TTL (s); hard_ttl_s = absolute cap.
        # Default to 30 min / 12 h if Zeus omits them (matches its own
        # NewSessionService defaults).
        idle_ttl = float(body.get("expires_in") or 1800)
        hard_ttl = float(body.get("hard_ttl_s") or 43200)
        async with _SESSION_LOCK:
            _SESSION_CACHE[cache_key] = {
                "sid": sid, "pwd": pwd, "idle_ttl": idle_ttl,
                "hard_deadline": now + hard_ttl, "last_used": now,
            }
        return {"X-Zeus-Session": sid}, f"basic→session {bucket}/{scope} {sid[:14]}…"
    raise RuntimeError(f"unknown auth mode: {mode}")


def merge_proxy_auth_headers(zcfg: dict, headers: dict | None) -> tuple[dict, tuple[str, str] | None]:
    """Attach proxy Basic auth for health probes when Zeus headers omit Authorization."""
    out = dict(headers or {})
    proxy = proxy_auth_tuple(zcfg)
    if proxy and "Authorization" not in out and "authorization" not in {k.lower() for k in out}:
        return out, proxy
    return out, None