"""ZeusRuntime — async CM wiring ports/adapters (no process-global HTTP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zeus_client_v2.adapters.secrets_env.store import EnvSecretStore
from zeus_client_v2.config.loader import load_runtime_config
from zeus_client_v2.config.models import RuntimeConfig
from zeus_client_v2.domain.journal import InMemoryJournal
from zeus_client_v2.ports.clock import Clock, SystemClock
from zeus_client_v2.ports.id_factory import IdFactory, UuidIdFactory
from zeus_client_v2.ports.secrets import SecretStorePort
from zeus_client_v2.security.redact import DefaultRedactor, default_redactor

__all__ = ["ZeusRuntime", "Services"]


@dataclass
class Services:
    """Internal dependency bundle (mutable only for close lifecycle)."""

    journal: InMemoryJournal = field(default_factory=InMemoryJournal)
    secrets: SecretStorePort = field(default_factory=EnvSecretStore)
    clock: Clock = field(default_factory=SystemClock)
    ids: IdFactory = field(default_factory=UuidIdFactory)
    redactor: DefaultRedactor = field(default_factory=default_redactor)
    zeus: Any = None
    llm: Any = None
    catalog: Any = None
    hub_debug: Any = None
    http: Any = None
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        http = self.http
        if http is not None and hasattr(http, "aclose"):
            await http.aclose()
        # Adapters may expose aclose as well
        for name in ("zeus", "llm", "hub_debug"):
            dep = getattr(self, name, None)
            if dep is not None and hasattr(dep, "aclose"):
                await dep.aclose()


class ZeusRuntime:
    """Bound runtime: config + services. Prefer ``async with`` / ``from_config``."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        services: Services | None = None,
        zeus: Any = None,
        llm: Any = None,
        catalog: Any = None,
        hub_debug: Any = None,
        secrets: SecretStorePort | None = None,
        http: Any = None,
        clock: Clock | None = None,
        ids: IdFactory | None = None,
        journal: InMemoryJournal | None = None,
    ) -> None:
        self.config = config
        svc = services or Services()
        if secrets is not None:
            svc.secrets = secrets
        if clock is not None:
            svc.clock = clock
        if ids is not None:
            svc.ids = ids
        if journal is not None:
            svc.journal = journal
        if zeus is not None:
            svc.zeus = zeus
        if llm is not None:
            svc.llm = llm
        if catalog is not None:
            svc.catalog = catalog
        if hub_debug is not None:
            svc.hub_debug = hub_debug
        if http is not None:
            svc.http = http
        self._services = svc
        self._entered = False

    @classmethod
    def from_config(
        cls,
        path: str | Path | None = None,
        *,
        profile: str = "development",
        env: dict[str, str] | None = None,
        **overrides: Any,
    ) -> ZeusRuntime:
        cfg = load_runtime_config(path, profile=profile, env=env)
        return cls(cfg, **overrides)

    @property
    def services(self) -> Services:
        return self._services

    @property
    def journal(self) -> InMemoryJournal:
        return self._services.journal

    @property
    def data(self) -> Any:
        """Data-plane facade (verbs / typeahead)."""
        from zeus_client_v2.api.data import DataAPI

        return DataAPI(self)

    @property
    def catalog(self) -> Any:
        """Catalog-plane facade (load / list / sync)."""
        from zeus_client_v2.api.catalog import CatalogAPI

        return CatalogAPI(self)

    @property
    def agent(self) -> Any:
        """Agent-plane facade (run_turn)."""
        from zeus_client_v2.api.agent import AgentAPI

        return AgentAPI(self)

    async def __aenter__(self) -> ZeusRuntime:
        self._entered = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._services.aclose()
