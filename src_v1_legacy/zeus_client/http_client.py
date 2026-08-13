"""Shared async HTTP client singleton."""
import httpx

from zeus_client.constants import UPSTREAM_TIMEOUT

_http: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    """Return the process-wide AsyncClient (raises if used before
    startup, which would be a wiring bug)."""
    if _http is None:  # pragma: no cover - defensive
        raise RuntimeError("HTTP client not initialised (lifespan not run)")
    return _http


async def init_http() -> None:
    """Create the process-wide AsyncClient (must run inside the event loop)."""
    global _http
    _http = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT),
    )


async def close_http() -> None:
    """Close the shared client on shutdown."""
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None
