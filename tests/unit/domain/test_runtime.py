"""ZeusRuntime lifecycle + ports wiring tests (ZCP-8)."""

from __future__ import annotations

import pytest

from zeus_client.config.models import RuntimeConfig
from zeus_client.runtime import Services, ZeusRuntime


class _FakeHttp:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeZeus:
    def __init__(self) -> None:
        self.closed = False

    async def resolve_auth(self, target, *, force: bool = False):  # noqa: ANN001
        from zeus_client.ports import AuthContext

        return AuthContext(headers={"X-Test": "1"}, mode="none")

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_runtime_from_config_development() -> None:
    async with ZeusRuntime.from_config(path=None, profile="development", env={}) as rt:
        assert rt.config.zeus.url
        assert rt.config.profile == "development"
        assert rt.journal is not None
        assert rt.services.secrets is not None


@pytest.mark.asyncio
async def test_runtime_closes_http_and_adapters() -> None:
    http = _FakeHttp()
    zeus = _FakeZeus()
    rt = ZeusRuntime(RuntimeConfig(), http=http, zeus=zeus)
    async with rt:
        assert http.closed is False
    assert http.closed is True
    assert zeus.closed is True


@pytest.mark.asyncio
async def test_runtime_override_injection() -> None:
    zeus = _FakeZeus()
    async with ZeusRuntime.from_config(env={}, zeus=zeus) as rt:
        assert rt.services.zeus is zeus
        auth = await rt.services.zeus.resolve_auth(rt.config.target)
        assert auth.headers["X-Test"] == "1"


def test_services_bundle_defaults() -> None:
    s = Services()
    assert s.journal is not None
    assert s.clock.now_ms() > 0
    assert s.ids.turn_id().startswith("turn_")
