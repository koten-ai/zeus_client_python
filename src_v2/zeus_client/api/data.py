"""Public data-plane facade on ZeusRuntime (verbs + later search)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from zeus_client_v2.application.data_verb import VerbResult, run_data_verb
from zeus_client_v2.domain.errors import ErrorCode, ZeusClientError

if TYPE_CHECKING:
    from zeus_client_v2.runtime import ZeusRuntime

__all__ = ["DataAPI"]


class DataAPI:
    """``rt.data.verb(...)`` / helpers — never exposes pipeline."""

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
        return await run_data_verb(
            zeus,
            name,
            body,
            target=self._rt.config.target,
            mode_header=mode_header or self._rt.config.settings.mode,
        )

    async def find(self, body: Mapping[str, Any] | None = None, **kwargs: Any) -> VerbResult:
        return await self.verb("find", body, **kwargs)

    async def get(self, body: Mapping[str, Any] | None = None, **kwargs: Any) -> VerbResult:
        return await self.verb("get", body, **kwargs)

    async def search_verb(self, body: Mapping[str, Any] | None = None, **kwargs: Any) -> VerbResult:
        """Raw V2 search body (typeahead product API is ``search`` use-case later)."""
        return await self.verb("search", body, **kwargs)
