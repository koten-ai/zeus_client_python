"""Per-runtime Zeus auth resolution — no process-global session cache on V2 paths."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config.models import DataTarget, ZeusEndpointConfig
from zeus_client.domain.errors import AuthError, ErrorCode
from zeus_client.ports import AuthContext
from zeus_client.ports.secrets import SecretStorePort

__all__ = ["ZeusAuthResolver"]


@dataclass
class ZeusAuthResolver:
    """Resolve auth headers for Zeus hops (instance-scoped; no module globals)."""

    endpoint: ZeusEndpointConfig
    secrets: SecretStorePort = field(default_factory=EnvSecretStore)

    async def resolve(
        self,
        target: DataTarget,
        *,
        force: bool = False,
    ) -> AuthContext:
        del force  # reserved for session re-mint (Phase 5)
        mode = (self.endpoint.auth_mode or "none").lower()
        if mode == "none":
            return AuthContext(headers={}, mode="none")
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
            return AuthContext(headers={"X-Zeus-Session": sid}, mode="session")
        if mode == "basic":
            user = self.endpoint.username or ""
            pwd_env = self.endpoint.password_env or "ZEUS_PASSWORD"
            pwd = self.secrets.get(pwd_env) if pwd_env else None
            if not user or not pwd:
                raise AuthError(
                    code=ErrorCode.ZEUS_AUTH_INCOMPLETE,
                    component="adapters.zeus_http.auth",
                    public_message="basic auth fields incomplete for auth_mode",
                    details={"username_set": bool(user), "password_env": pwd_env},
                )
            token = base64.b64encode(f"{user}:{pwd}".encode()).decode("ascii")
            return AuthContext(
                headers={"Authorization": f"Basic {token}"},
                mode="basic",
            )
        raise AuthError(
            code=ErrorCode.ZEUS_AUTH_MODE_INVALID,
            component="adapters.zeus_http.auth",
            public_message=f"zeus.auth_mode invalid: {mode!r}",
        )
