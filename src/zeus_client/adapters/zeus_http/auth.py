"""Per-runtime Zeus auth resolution — no process-global session cache on V2 paths."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.errors import AuthError, ErrorCode
from zeus_client.ports import AuthContext
from zeus_client.ports.secrets import SecretStorePort

logger = logging.getLogger("zeus_client.auth")

__all__ = ["ZeusAuthResolver"]

_SESSION_IDLE_MARGIN_S = 30.0


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
