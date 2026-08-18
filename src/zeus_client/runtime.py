"""ZeusRuntime — async CM wiring ports/adapters (no process-global HTTP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config.loader import load_runtime_config
from zeus_client.config.models import RuntimeConfig
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.observability.metrics import InMemoryMetrics, MetricsPort
from zeus_client.observability.rate_limit import TokenBucketLimiter
from zeus_client.ports.clock import Clock, SystemClock
from zeus_client.ports.id_factory import IdFactory, UuidIdFactory
from zeus_client.ports.secrets import SecretStorePort
from zeus_client.security.redact import DefaultRedactor, default_redactor

__all__ = ["ZeusRuntime", "Services"]


@dataclass
class Services:
    """Internal dependency bundle (mutable only for close lifecycle)."""

    journal: InMemoryJournal = field(default_factory=InMemoryJournal)
    secrets: SecretStorePort = field(default_factory=EnvSecretStore)
    clock: Clock = field(default_factory=SystemClock)
    ids: IdFactory = field(default_factory=UuidIdFactory)
    redactor: DefaultRedactor = field(default_factory=default_redactor)
    metrics: MetricsPort = field(default_factory=InMemoryMetrics)
    rate_limiter: TokenBucketLimiter = field(default_factory=TokenBucketLimiter)
    zeus: Any = None
    llm: Any = None
    catalog: Any = None
    hub_debug: Any = None
    http: Any = None
    otlp: Any = None
    session_lifecycle: Any = None
    jobs: Any = None
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        http = self.http
        if http is not None and hasattr(http, "aclose"):
            await http.aclose()
        # Adapters may expose aclose as well
        for name in ("zeus", "llm", "hub_debug", "otlp"):
            dep = getattr(self, name, None)
            if dep is not None and hasattr(dep, "aclose"):
                await dep.aclose()
            elif dep is not None and hasattr(dep, "shutdown"):
                dep.shutdown()


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
        metrics: MetricsPort | None = None,
        rate_limiter: TokenBucketLimiter | None = None,
        otlp: Any = None,
        jobs: Any = None,
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
        if metrics is not None:
            svc.metrics = metrics
        if rate_limiter is not None:
            svc.rate_limiter = rate_limiter
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
        if otlp is not None:
            svc.otlp = otlp
        if jobs is not None:
            svc.jobs = jobs
        self._services = svc
        self._entered = False
        self._configure_rate_limits()

    def _configure_rate_limits(self) -> None:
        rl = self.config.rate_limit
        if rl.typeahead_enabled:
            self._services.rate_limiter.configure(
                "typeahead",
                rate=float(rl.typeahead_rps),
                burst=float(rl.typeahead_burst),
            )

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
    def metrics(self) -> MetricsPort:
        return self._services.metrics

    @property
    def data(self) -> Any:
        """Data-plane facade (verbs / typeahead)."""
        from zeus_client.api.data import DataAPI

        return DataAPI(self)

    @property
    def catalog(self) -> Any:
        """Catalog-plane facade (load / list / sync)."""
        from zeus_client.api.catalog import CatalogAPI

        return CatalogAPI(self)

    @property
    def agent(self) -> Any:
        """Agent-plane facade (run_turn)."""
        from zeus_client.api.agent import AgentAPI

        return AgentAPI(self)

    @property
    def debug(self) -> Any:
        """Debug plane — journal export, spans, transport replay."""
        from zeus_client.api.debug import DebugAPI

        return DebugAPI(self)

    @property
    def units(self) -> Any:
        """Mode 3 unit adapters (isolated agent_turn / zeus_direct)."""
        from zeus_client.api.units import UnitsAPI

        return UnitsAPI(self)

    @property
    def jobs(self) -> Any:
        """Mode 3 jobs client (fail-closed without a job runtime host)."""
        from zeus_client.api.jobs import JobsAPI

        return JobsAPI(self)

    async def __aenter__(self) -> ZeusRuntime:
        self._entered = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._services.aclose()
