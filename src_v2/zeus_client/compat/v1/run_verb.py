"""Deprecated V1-shaped direct verb entry → ``rt.data.verb`` / ``find``."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Mapping

from zeus_client_v2.application.data_verb import VerbResult

if TYPE_CHECKING:
    from zeus_client_v2.runtime import ZeusRuntime

__all__ = ["run_verb", "run_find"]

_DEPRECATION = (
    "zeus_client_v2.compat.v1.run_verb is deprecated; "
    "use ZeusRuntime.data.verb / .find / .get instead"
)


async def run_verb(
    verb: str,
    args: Mapping[str, Any] | None = None,
    *,
    runtime: ZeusRuntime,
    mode_header: str | None = None,
    # Ignored V1 leftovers:
    zeus_url: str | None = None,
    bucket: str | None = None,
    scope: str | None = None,
    collection: str | None = None,
    zeus_headers: Mapping[str, str] | None = None,
    zcfg: Mapping[str, Any] | None = None,
    **_ignored: Any,
) -> VerbResult:
    """Deprecated shim: call ``runtime.data.verb``."""
    warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
    _ = (zeus_url, bucket, scope, collection, zeus_headers, zcfg)
    return await runtime.data.verb(verb, args, mode_header=mode_header)


async def run_find(
    args: Mapping[str, Any] | None = None,
    *,
    runtime: ZeusRuntime,
    mode_header: str | None = None,
    **kwargs: Any,
) -> VerbResult:
    """Deprecated shim: ``run_verb(\"find\", ...)``."""
    return await run_verb("find", args, runtime=runtime, mode_header=mode_header, **kwargs)
