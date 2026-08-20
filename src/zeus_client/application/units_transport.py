"""Per-unit Zeus transport overrides (URL + auth env names)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from zeus_client.domain.jobs import UnitConfig
from zeus_client.ports import VerbHopResult, VerbRequest

__all__ = [
    "UnitScopedZeusPort",
    "same_zeus_host",
    "verb_overrides",
]


def same_zeus_host(unit_url: str | None, process_url: str | None) -> bool:
    left = (unit_url or "").rstrip("/")
    right = (process_url or "").rstrip("/")
    if not left or not right:
        return True
    return left == right


def verb_overrides(unit: UnitConfig) -> dict[str, str | None]:
    return {
        "base_url": unit.zeus_url,
        "auth_mode": unit.auth_mode,
        "password_env": unit.password_env,
        "token_env": unit.token_env,
        "username": unit.username,
    }


def patch_verb_request(req: VerbRequest, unit: UnitConfig) -> VerbRequest:
    over = verb_overrides(unit)
    return replace(
        req,
        base_url=over["base_url"] or req.base_url,
        auth_mode=over["auth_mode"] if over["auth_mode"] is not None else req.auth_mode,
        password_env=(
            over["password_env"] if over["password_env"] is not None else req.password_env
        ),
        token_env=over["token_env"] if over["token_env"] is not None else req.token_env,
        username=over["username"] if over["username"] is not None else req.username,
    )


class UnitScopedZeusPort:
    """Wraps ZeusPort and stamps each hop with the unit URL/auth names."""

    def __init__(self, inner: Any, unit: UnitConfig) -> None:
        self._inner = inner
        self._unit = unit

    async def resolve_auth(self, target: Any, *, force: bool = False) -> Any:
        return await self._inner.resolve_auth(target, force=force)

    async def call_verb(self, req: VerbRequest) -> VerbHopResult:
        return await self._inner.call_verb(patch_verb_request(req, self._unit))
