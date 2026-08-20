"""ZeusRuntime — async CM wiring ports/adapters (no process-global HTTP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.config.loader import load_runtime_config
from zeus_client.config.models import LlmProviderConfig, RuntimeConfig
from zeus_client.domain.journal import InMemoryJournal
from zeus_client.observability.logging import configure_family_logger
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
    catalog_remote: Any = None
    hub_debug: Any = None
    http: Any = None
    otlp: Any = None
    session_lifecycle: Any = None
    jobs: Any = None
    agent_memory: Any = None
    extra_llms: list[Any] = field(default_factory=list)
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        http = self.http
        if http is not None and hasattr(http, "aclose"):
            await http.aclose()
        # Adapters may expose aclose as well
        for name in (
            "zeus",
            "llm",
            "hub_debug",
            "otlp",
            "jobs",
            "catalog_remote",
            "agent_memory",
        ):
            dep = getattr(self, name, None)
            if dep is not None and hasattr(dep, "aclose"):
                await dep.aclose()
            elif dep is not None and hasattr(dep, "shutdown"):
                dep.shutdown()
        life = self.session_lifecycle
        if life is not None:
            sess_client = getattr(life, "client", None)
            if sess_client is not None and hasattr(sess_client, "aclose"):
                await sess_client.aclose()
        for dep in list(self.extra_llms):
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
        catalog_remote: Any = None,
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
        agent_memory: Any = None,
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
        if catalog_remote is not None:
            svc.catalog_remote = catalog_remote
        if hub_debug is not None:
            svc.hub_debug = hub_debug
        if http is not None:
            svc.http = http
        if otlp is not None:
            svc.otlp = otlp
        if jobs is not None:
            svc.jobs = jobs
        if agent_memory is not None:
            svc.agent_memory = agent_memory
        self._services = svc
        self._entered = False
        self._configure_rate_limits()
        self._configure_logging()
        self._ensure_session_lifecycle()
        self._ensure_agent_memory()
        self._ensure_otlp()

    def llm_for_slice(self, slice: Any) -> Any:
        """Return process LLM, or a temporary client when worker key/host differs."""
        from zeus_client.domain.llm_roles import ResolvedLlmSlice

        if not isinstance(slice, ResolvedLlmSlice):
            return self.services.llm
        base = self.config.llm
        same_key = (slice.api_key_env or "") == (base.api_key_env or "")
        same_url = (slice.base_url or base.base_url) == base.base_url
        if same_key and same_url:
            return self.services.llm
        from zeus_client.adapters.llm_openai_compatible.client import OpenAICompatibleLlmClient

        cfg = LlmProviderConfig(
            provider=slice.provider or base.provider,
            base_url=slice.base_url or base.base_url,
            model=slice.model or base.model,
            api_key_env=slice.api_key_env or base.api_key_env,
            context_window_tokens=base.context_window_tokens,
            context_soft_limit=base.context_soft_limit,
            timeout_s=base.timeout_s,
            roles=base.roles,
        )
        client = OpenAICompatibleLlmClient(
            config=cfg,
            secrets=self.services.secrets,
            journal=self.journal,
            retry=self.config.retry,
        )
        self._services.extra_llms.append(client)
        return client

    def _configure_rate_limits(self) -> None:
        rl = self.config.rate_limit
        if rl.typeahead_enabled:
            self._services.rate_limiter.configure(
                "typeahead",
                rate=float(rl.typeahead_rps),
                burst=float(rl.typeahead_burst),
            )

    def _configure_logging(self) -> None:
        from zeus_client._version import __version__ as PACKAGE_VERSION

        pol = self.config.logging
        configure_family_logger(
            level=pol.level,
            redact=pol.redact and self.config.redaction.enabled,
            service_name=pol.service_name,
            service_version=pol.service_version or PACKAGE_VERSION,
            preview_max_chars=self.config.redaction.preview_max_chars,
            redactor=self._services.redactor,
        )

    def _ensure_session_lifecycle(self) -> None:
        if self._services.session_lifecycle is not None:
            return
        if not self.config.settings.durable_sessions:
            return
        from zeus_client.adapters.zeus_http.session import HttpxSessionClient
        from zeus_client.application.session_lifecycle import SessionLifecycle

        http = getattr(self._services.zeus, "client", None)
        client = HttpxSessionClient(
            endpoint=self.config.zeus,
            secrets=self._services.secrets,
            client=http if http is not None else None,
            identity=self.config.client,
        )
        self._services.session_lifecycle = SessionLifecycle(
            client=client,
            target=self.config.target,
        )

    def _ensure_agent_memory(self) -> None:
        if self._services.agent_memory is not None:
            return
        if not self.config.zeus.url:
            return
        from zeus_client.adapters.zeus_http.agent_memory import HttpxAgentMemoryClient

        http = getattr(self._services.zeus, "client", None)
        self._services.agent_memory = HttpxAgentMemoryClient(
            endpoint=self.config.zeus,
            secrets=self._services.secrets,
            journal=self._services.journal,
            client=http if http is not None else None,
        )

    def _ensure_otlp(self) -> None:
        if self._services.otlp is not None:
            return
        pol = self.config.logging
        from zeus_client.adapters.otlp.exporter import try_build_otlp_exporter

        self._services.otlp = try_build_otlp_exporter(
            endpoint=pol.otel_endpoint,
            service_name=pol.service_name,
            enabled=bool(pol.otel_enabled and pol.otel_endpoint),
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
        if "jobs" not in overrides and cfg.jobs.host_url:
            from zeus_client.adapters.jobs_http.client import HttpxJobRuntime

            overrides["jobs"] = HttpxJobRuntime(cfg.jobs.host_url)
        rt = cls(cfg, **overrides)
        if rt.services.catalog_remote is None and rt.config.zeus.url:
            from zeus_client.adapters.zeus_http.catalog_remote import HttpxCatalogRemote

            rt.services.catalog_remote = HttpxCatalogRemote(
                endpoint=rt.config.zeus,
                secrets=rt.services.secrets,
            )
        return rt

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
    def session(self) -> Any:
        """Session-plane facade (semantic cache + flags)."""
        from zeus_client.api.session import SessionAPI

        return SessionAPI(self)

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
