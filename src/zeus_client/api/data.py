"""Public data-plane facade on ZeusRuntime (verbs + typeahead)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from zeus_client.application.data_verb import VerbResult, run_data_verb
from zeus_client.application.typeahead import (
    SuggestOptions,
    SuggestResult,
    run_typeahead_search,
)
from zeus_client.domain.errors import ErrorCode, ZeusClientError

if TYPE_CHECKING:
    from zeus_client.runtime import ZeusRuntime

__all__ = ["DataAPI"]


class DataAPI:
    """``rt.data.verb(...)`` / ``rt.data.search(...)`` — never exposes pipeline."""

    def __init__(self, runtime: ZeusRuntime) -> None:
        self._rt = runtime

    async def verb(
        self,
        name: str,
        body: Mapping[str, Any] | None = None,
        *,
        mode_header: str | None = None,
    ) -> VerbResult:
        zeus = self._rt.services.zeus
        if zeus is None:
            raise ZeusClientError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="api.data",
                public_message="Zeus port not wired on runtime",
            )
        result = await run_data_verb(
            zeus,
            name,
            body,
            target=self._rt.config.target,
            mode_header=mode_header or self._rt.config.settings.mode,
        )
        metrics = self._rt.services.metrics
        status_class = f"{result.status_code // 100}xx" if result.status_code else "err"
        metrics.incr(
            "zeus_client_zeus_hops_total",
            labels={"verb": name, "status_class": status_class},
        )
        if not result.ok:
            metrics.incr(
                "zeus_client_errors_total",
                labels={"code": "zeus_verb_failed"},
            )
        return result

    async def find(self, body: Mapping[str, Any] | None = None, **kwargs: Any) -> VerbResult:
        return await self.verb("find", body, **kwargs)

    async def get(self, body: Mapping[str, Any] | None = None, **kwargs: Any) -> VerbResult:
        return await self.verb("get", body, **kwargs)

    async def search_verb(self, body: Mapping[str, Any] | None = None, **kwargs: Any) -> VerbResult:
        """Raw V2 search body (typeahead product API is ``search``)."""
        return await self.verb("search", body, **kwargs)

    async def search(
        self,
        query: str,
        *,
        options: SuggestOptions | None = None,
    ) -> SuggestResult:
        """No-LLM typeahead (FTS). Never agent-per-keystroke. Rate-limited per runtime."""
        zeus = self._rt.services.zeus
        if zeus is None:
            raise ZeusClientError(
                code=ErrorCode.NOT_IMPLEMENTED,
                component="api.data",
                public_message="Zeus port not wired on runtime",
            )
        rl = self._rt.config.rate_limit
        if rl.typeahead_enabled and not self._rt.services.rate_limiter.allow("typeahead"):
            self._rt.services.metrics.incr(
                "zeus_client_rate_limited_total",
                labels={"surface": "typeahead"},
            )
            raise ZeusClientError(
                code=ErrorCode.CLIENT_RATE_LIMITED,
                component="api.data.search",
                public_message="rate limited (client)",
                details={
                    "surface": "typeahead",
                    "rps": rl.typeahead_rps,
                    "burst": rl.typeahead_burst,
                },
            )
        result = await run_typeahead_search(
            zeus,
            query,
            target=self._rt.config.target,
            options=options,
        )
        self._rt.services.metrics.incr(
            "zeus_client_typeahead_total",
            labels={"source": result.source or "unknown"},
        )
        return result
