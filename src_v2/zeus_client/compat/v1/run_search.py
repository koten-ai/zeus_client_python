"""Deprecated V1-shaped typeahead entry → ``rt.data.search``."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Mapping

from zeus_client_v2.application.typeahead import SuggestOptions, SuggestResult
from zeus_client_v2.config.models import DataTarget

if TYPE_CHECKING:
    from zeus_client_v2.runtime import ZeusRuntime

__all__ = ["run_search"]

_DEPRECATION = (
    "zeus_client_v2.compat.v1.run_search is deprecated; "
    "use ZeusRuntime.data.search(...) instead"
)


async def run_search(
    query: str,
    *,
    runtime: ZeusRuntime,
    options: SuggestOptions | None = None,
    bucket: str | None = None,
    scope: str | None = None,
    collection: str | None = None,
    # Ignored V1 leftovers:
    zeus_url: str | None = None,
    zeus_headers: Mapping[str, str] | None = None,
    zcfg: Mapping[str, Any] | None = None,
    couchbase: Any = None,
    **_ignored: Any,
) -> SuggestResult:
    """Deprecated shim: call ``runtime.data.search``.

    Target overrides temporarily mutate nothing on the runtime — pass a runtime
    already bound to the desired ``DataTarget``, or use ``rt.data.search`` with
    a runtime constructed for that sample.
    """
    warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
    _ = (zeus_url, zeus_headers, zcfg, couchbase)
    if bucket or scope or collection:
        # Soft note via options is not available; document target on runtime.
        # Constructing a one-shot RuntimeConfig override is out of shim scope.
        _ = DataTarget(
            bucket=bucket or runtime.config.target.bucket,
            scope=scope or runtime.config.target.scope,
            collection=collection or runtime.config.target.collection,
        )
    return await runtime.data.search(query, options=options)
