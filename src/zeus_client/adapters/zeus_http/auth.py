"""Per-runtime Zeus auth resolution — no process-global session cache on V2 paths."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config.models import (
    DataTarget,
    M2MClientConfig,
    ZeusEndpointConfig,
    auth_mode_disabled_reason,
)
from zeus_client.domain.errors import AuthError, ErrorCode
from zeus_client.ports import AuthContext
from zeus_client.ports.secrets import SecretStorePort

logger = logging.getLogger("zeus_client.auth")

__all__ = ["ZeusAuthResolver"]

_SESSION_IDLE_MARGIN_S = 30.0
_PAT_PREFIX = "zeus_pat_"


@dataclass
class _CachedSid:
    sid: str
    pwd: str
    idle_ttl: float
    hard_deadline: float
    last_used: float


@dataclass
class ZeusAuthResolver:
    """Resolve auth headers for Zeus hops (instance-scoped; no module globals)."""

    endpoint: ZeusEndpointConfig
    secrets: SecretStorePort = field(default_factory=EnvSecretStore)
    client: httpx.AsyncClient | None = None
    _owns_client: bool = False
    _cache: dict[tuple[str, str, str, str], _CachedSid] = field(default_factory=dict)

    async def aclose(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()
            self.client = None

    async def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.endpoint.timeout_s)
            self._owns_client = True
        return self.client

    def _scope_user_pwd(self, target: DataTarget) -> tuple[str, str, str]:
        key = f"{target.bucket}/{target.scope}"
        scoped = (self.endpoint.scope_credentials or {}).get(key) or {}
        user = str(scoped.get("username") or self.endpoint.username or "")
        pwd_env = str(scoped.get("password_env") or self.endpoint.password_env or "ZEUS_PASSWORD")
        pwd = self.secrets.get(pwd_env) if pwd_env else None
        return user, pwd or "", pwd_env

    async def resolve(
        self,
        target: DataTarget,
        *,
        force: bool = False,
    ) -> AuthContext:
        mode = (self.endpoint.auth_mode or "none").lower()
        if mode == "none":
            return AuthContext(headers={}, mode="none")
        if mode == "certificate":
            raise AuthError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="adapters.zeus_http.auth",
                public_message=(
                    "certificate/mTLS auth_mode is documented but not implemented; "
                    "set cert_file / key_file_env on ZeusEndpointConfig"
                ),
                details={
                    "cert_file": self.endpoint.cert_file,
                    "key_file_env": self.endpoint.key_file_env,
                },
            )
        if mode == "bearer":
            env_name = self.endpoint.token_env or "ZEUS_BEARER_TOKEN"
            tok = self.secrets.get(env_name)
            if not tok:
                raise AuthError(
                    code=ErrorCode.AUTH_FAILED,
                    component="adapters.zeus_http.auth",
                    public_message="bearer mode selected but token env empty",
                    details={"token_env": env_name},
                )
            logger.info("zeus.auth resolved mode=bearer token_env=%s", env_name)
            return AuthContext(headers={"Authorization": f"Bearer {tok}"}, mode="bearer")
        if mode == "session":
            env_name = self.endpoint.token_env or "ZEUS_SESSION_ID"
            sid = self.secrets.get(env_name)
            if not sid:
                raise AuthError(
                    code=ErrorCode.AUTH_FAILED,
                    component="adapters.zeus_http.auth",
                    public_message="session mode selected but session id env empty",
                    details={"token_env": env_name},
                )
            logger.info("zeus.auth resolved mode=session")
            return AuthContext(headers={"X-Zeus-Session": sid}, mode="session")
        if mode == "basic":
            return await self._resolve_basic(target, force=force)
        if reason := auth_mode_disabled_reason(mode):
            raise AuthError(
                code=ErrorCode.FEATURE_DISABLED,
                component="adapters.zeus_http.auth",
                public_message=reason,
                details={"auth_mode": mode},
            )
        if mode == "pat":
            return await self._resolve_pat(target, force=force)
        if mode == "m2m":
            return await self._resolve_m2m(target, force=force)
        raise AuthError(
            code=ErrorCode.ZEUS_AUTH_MODE_INVALID,
            component="adapters.zeus_http.auth",
            public_message=f"zeus.auth_mode invalid: {mode!r}",
        )

    async def _resolve_basic(self, target: DataTarget, *, force: bool) -> AuthContext:
        if not target.bucket or not target.scope:
            raise AuthError(
                code=ErrorCode.ZEUS_AUTH_INCOMPLETE,
                component="adapters.zeus_http.auth",
                public_message=(
                    "basic mode needs bucket+scope for per-scope "
                    "POST /v1/{bucket}/{scope}/auth/session"
                ),
            )
        user, pwd, pwd_env = self._scope_user_pwd(target)
        if not user or not pwd:
            raise AuthError(
                code=ErrorCode.ZEUS_AUTH_INCOMPLETE,
                component="adapters.zeus_http.auth",
                public_message="basic auth fields incomplete for auth_mode",
                details={"username_set": bool(user), "password_env": pwd_env},
            )
        cache_key = (self.endpoint.url, target.bucket, target.scope, user)
        now = time.time()
        if not force:
            ent = self._cache.get(cache_key)
            if (
                ent
                and ent.pwd == pwd
                and now < ent.hard_deadline
                and (now - ent.last_used) < (ent.idle_ttl - _SESSION_IDLE_MARGIN_S)
            ):
                ent.last_used = now
                logger.info(
                    "zeus.auth basic cache hit bucket=%s scope=%s sid=%s…",
                    target.bucket,
                    target.scope,
                    ent.sid[:12],
                )
                return AuthContext(headers={"X-Zeus-Session": ent.sid}, mode="basic")

        url = f"{self.endpoint.url.rstrip('/')}/v1/{target.bucket}/{target.scope}/auth/session"
        client = await self._http()
        try:
            r = await client.post(url, auth=(user, pwd), timeout=self.endpoint.timeout_s)
        except httpx.HTTPError as exc:
            logger.warning(
                "zeus.auth basic login unreachable bucket=%s scope=%s err=%s",
                target.bucket,
                target.scope,
                type(exc).__name__,
            )
            raise AuthError(
                code=ErrorCode.AUTH_SESSION_UNAVAILABLE,
                component="adapters.zeus_http.auth",
                public_message=f"Zeus basic login unreachable: {type(exc).__name__}",
                details={"bucket": target.bucket, "scope": target.scope},
            ) from exc
        if r.status_code != 200:
            logger.error(
                "zeus.auth basic login failed bucket=%s scope=%s status=%s",
                target.bucket,
                target.scope,
                r.status_code,
            )
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message=f"Zeus basic login failed HTTP {r.status_code}",
                details={"status_code": r.status_code},
            )
        try:
            body = r.json()
        except Exception as exc:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="Zeus login returned invalid JSON",
            ) from exc
        sid = str((body or {}).get("session_id") or "")
        if not sid:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="Zeus login returned no session_id",
            )
        idle_ttl = float((body or {}).get("expires_in") or 1800)
        hard_ttl = float((body or {}).get("hard_ttl_s") or 43200)
        self._cache[cache_key] = _CachedSid(
            sid=sid,
            pwd=pwd,
            idle_ttl=idle_ttl,
            hard_deadline=now + hard_ttl,
            last_used=now,
        )
        logger.info(
            "zeus.auth basic session minted bucket=%s scope=%s sid=%s…",
            target.bucket,
            target.scope,
            sid[:12],
        )
        return AuthContext(headers={"X-Zeus-Session": sid}, mode="basic")

    async def _resolve_pat(self, target: DataTarget, *, force: bool) -> AuthContext:
        """Mint a session from a PAT, then send only X-Zeus-Session.

        A token that does not start with ``zeus_pat_`` is refused locally.
        It is not posted, so Zeus cannot route it into the M2M JWT verifier.
        """
        env_name = self.endpoint.token_env or "ZEUS_PAT"
        token = self.secrets.get(env_name) or ""
        if not token:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="pat mode selected but token env empty",
                details={"token_env": env_name},
            )
        if not token.startswith(_PAT_PREFIX):
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message=("pat token must start with zeus_pat_; refusing to send it to Zeus"),
                details={"token_env": env_name},
            )
        if not target.bucket or not target.scope:
            raise AuthError(
                code=ErrorCode.ZEUS_AUTH_INCOMPLETE,
                component="adapters.zeus_http.auth",
                public_message=(
                    "pat mode needs bucket+scope for POST /v1/{bucket}/{scope}/auth/session"
                ),
            )
        cache_key = (self.endpoint.url, target.bucket, target.scope, "pat")
        now = time.time()
        if not force:
            ent = self._cache.get(cache_key)
            if (
                ent
                and ent.pwd == token
                and now < ent.hard_deadline
                and (now - ent.last_used) < (ent.idle_ttl - _SESSION_IDLE_MARGIN_S)
            ):
                ent.last_used = now
                logger.info(
                    "zeus.auth pat cache hit bucket=%s scope=%s sid=%s…",
                    target.bucket,
                    target.scope,
                    ent.sid[:12],
                )
                return AuthContext(headers={"X-Zeus-Session": ent.sid}, mode="pat")

        url = f"{self.endpoint.url.rstrip('/')}/v1/{target.bucket}/{target.scope}/auth/session"
        client = await self._http()
        try:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.endpoint.timeout_s,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "zeus.auth pat login unreachable bucket=%s scope=%s err=%s",
                target.bucket,
                target.scope,
                type(exc).__name__,
            )
            raise AuthError(
                code=ErrorCode.AUTH_SESSION_UNAVAILABLE,
                component="adapters.zeus_http.auth",
                public_message=f"Zeus PAT login unreachable: {type(exc).__name__}",
                details={"bucket": target.bucket, "scope": target.scope},
            ) from exc
        if r.status_code != 200:
            logger.error(
                "zeus.auth pat login failed bucket=%s scope=%s status=%s",
                target.bucket,
                target.scope,
                r.status_code,
            )
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message=f"Zeus PAT login failed HTTP {r.status_code}",
                details={"status_code": r.status_code},
            )
        try:
            body = r.json()
        except Exception as exc:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="Zeus login returned invalid JSON",
            ) from exc
        sid = str((body or {}).get("session_id") or "")
        if not sid:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="Zeus login returned no session_id",
            )
        idle_ttl = float((body or {}).get("expires_in") or 1800)
        hard_ttl = float((body or {}).get("hard_ttl_s") or 43200)
        self._cache[cache_key] = _CachedSid(
            sid=sid,
            pwd=token,
            idle_ttl=idle_ttl,
            hard_deadline=now + hard_ttl,
            last_used=now,
        )
        logger.info(
            "zeus.auth pat session minted bucket=%s scope=%s sid=%s…",
            target.bucket,
            target.scope,
            sid[:12],
        )
        return AuthContext(headers={"X-Zeus-Session": sid}, mode="pat")

    async def _resolve_m2m(self, target: DataTarget, *, force: bool) -> AuthContext:
        """Fetch an IdP JWT, mint a Zeus session, then send only X-Zeus-Session.

        The client secret stays in the environment. Zeus only verifies the JWT.
        An unset issuer fails closed and does not call the IdP or Zeus.
        """
        cfg = self.endpoint.m2m
        issuer = (cfg.issuer or "").strip()
        if not issuer:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="m2m issuer is unset",
            )
        audience = (cfg.audience or "").strip()
        if not audience:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="m2m audience is unset",
            )
        client_id = (cfg.client_id or "").strip()
        if not client_id:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="m2m client_id is unset",
            )
        secret_env = cfg.client_secret_env or "ZEUS_M2M_CLIENT_SECRET"
        secret = self.secrets.get(secret_env) or ""
        if not secret:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="m2m client secret env empty",
                details={"client_secret_env": secret_env},
            )

        cache_key = (self.endpoint.url, target.bucket, target.scope, f"m2m:{client_id}")
        now = time.time()
        if not force:
            ent = self._cache.get(cache_key)
            if (
                ent
                and ent.pwd == secret
                and now < ent.hard_deadline
                and (now - ent.last_used) < (ent.idle_ttl - _SESSION_IDLE_MARGIN_S)
            ):
                ent.last_used = now
                logger.info(
                    "zeus.auth m2m cache hit bucket=%s scope=%s sid=%s…",
                    target.bucket,
                    target.scope,
                    ent.sid[:12],
                )
                return AuthContext(headers={"X-Zeus-Session": ent.sid}, mode="m2m")

        jwt = await self._fetch_m2m_jwt(cfg, issuer, audience, client_id, secret)
        root = self.endpoint.url.rstrip("/")
        if target.bucket and target.scope:
            url = f"{root}/v1/{target.bucket}/{target.scope}/auth/session"
        else:
            url = f"{root}/v1/auth/session"
        client = await self._http()
        try:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {jwt}"},
                timeout=self.endpoint.timeout_s,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "zeus.auth m2m login unreachable bucket=%s scope=%s err=%s",
                target.bucket,
                target.scope,
                type(exc).__name__,
            )
            raise AuthError(
                code=ErrorCode.AUTH_SESSION_UNAVAILABLE,
                component="adapters.zeus_http.auth",
                public_message=f"Zeus M2M login unreachable: {type(exc).__name__}",
                details={"bucket": target.bucket, "scope": target.scope},
            ) from exc
        if r.status_code != 200:
            logger.error(
                "zeus.auth m2m login failed bucket=%s scope=%s status=%s",
                target.bucket,
                target.scope,
                r.status_code,
            )
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message=f"Zeus M2M login failed HTTP {r.status_code}",
                details={"status_code": r.status_code},
            )
        try:
            body = r.json()
        except Exception as exc:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="Zeus login returned invalid JSON",
            ) from exc
        sid = str((body or {}).get("session_id") or "")
        if not sid:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="Zeus login returned no session_id",
            )
        idle_ttl = float((body or {}).get("expires_in") or 1800)
        hard_ttl = float((body or {}).get("hard_ttl_s") or 43200)
        self._cache[cache_key] = _CachedSid(
            sid=sid,
            pwd=secret,
            idle_ttl=idle_ttl,
            hard_deadline=now + hard_ttl,
            last_used=now,
        )
        logger.info(
            "zeus.auth m2m session minted bucket=%s scope=%s sid=%s…",
            target.bucket,
            target.scope,
            sid[:12],
        )
        return AuthContext(headers={"X-Zeus-Session": sid}, mode="m2m")

    async def _fetch_m2m_jwt(
        self,
        cfg: M2MClientConfig,
        issuer: str,
        audience: str,
        client_id: str,
        secret: str,
    ) -> str:
        token_url = (cfg.token_url or "").strip() or await self._discover_token_url(issuer)
        client = await self._http()
        form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            "audience": audience,
        }
        if (cfg.scope or "").strip():
            form["scope"] = cfg.scope.strip()
        try:
            r = await client.post(token_url, data=form, timeout=self.endpoint.timeout_s)
        except httpx.HTTPError as exc:
            raise AuthError(
                code=ErrorCode.AUTH_SESSION_UNAVAILABLE,
                component="adapters.zeus_http.auth",
                public_message=f"IdP token endpoint unreachable: {type(exc).__name__}",
                details={"issuer": issuer},
            ) from exc
        if r.status_code != 200:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message=f"IdP token request failed HTTP {r.status_code}",
                details={"status_code": r.status_code},
            )
        try:
            body = r.json()
        except Exception as exc:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="IdP token response was not JSON",
            ) from exc
        token = str((body or {}).get("access_token") or "")
        if not token:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="IdP token response missing access_token",
            )
        logger.info("zeus.auth m2m jwt fetched issuer=%s client_id=%s", issuer, client_id)
        return token

    async def _discover_token_url(self, issuer: str) -> str:
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        client = await self._http()
        try:
            r = await client.get(url, timeout=self.endpoint.timeout_s)
        except httpx.HTTPError as exc:
            raise AuthError(
                code=ErrorCode.AUTH_SESSION_UNAVAILABLE,
                component="adapters.zeus_http.auth",
                public_message=f"IdP discovery unreachable: {type(exc).__name__}",
                details={"issuer": issuer},
            ) from exc
        if r.status_code != 200:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message=f"IdP discovery failed HTTP {r.status_code}",
                details={"status_code": r.status_code},
            )
        try:
            body = r.json()
        except Exception as exc:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="IdP discovery response was not JSON",
            ) from exc
        token_url = str((body or {}).get("token_endpoint") or "").strip()
        if not token_url:
            raise AuthError(
                code=ErrorCode.AUTH_FAILED,
                component="adapters.zeus_http.auth",
                public_message="IdP discovery missing token_endpoint",
            )
        return token_url
