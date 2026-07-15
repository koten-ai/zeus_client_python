"""Background asyncio loop so Flask (sync) can call the zeus_client async stack.

Recipes R02–R04. Aligned with demo_travel_sample/src/travel_planner/async_runner.py.
For FastAPI, prefer native async + lifespan (RECIPES.md R02b) instead.
"""
from __future__ import annotations

import asyncio
import atexit
import threading
from pathlib import Path

# TODO: from my_package.paths import PROJECT_ROOT
# TODO: from my_package.zeus_config import configure_zeus_client
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_loop: asyncio.AbstractEventLoop | None = None
_started = False


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is not None:
        return _loop

    loop = asyncio.new_event_loop()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=run, name="async-runner", daemon=True).start()
    _loop = loop
    return loop


def run_coro(coro, timeout: float = 600):
    """Run an async coroutine on the persistent background loop."""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _sync_chat_requests_on_startup(cfg: dict) -> None:
    """Pull chat_request catalogs from Zeus when config enables on_startup (R04)."""
    sync_cfg = cfg.get("chat_requests_sync") or {}
    if not sync_cfg.get("on_startup"):
        return

    from zeus_client import logger, sync_chat_requests

    try:
        result = run_coro(sync_chat_requests(cfg))
    except Exception as e:
        logger.warning("startup chat_requests sync failed: %s", e)
        return

    if result.synced:
        logger.info(
            "startup chat_requests sync: updated %d catalog(s)",
            len(result.synced),
        )
    if result.skipped:
        logger.info(
            "startup chat_requests sync: skipped %d unchanged catalog(s)",
            len(result.skipped),
        )
    if result.errors:
        logger.warning(
            "startup chat_requests sync: %d error(s): %s",
            len(result.errors),
            result.errors,
        )


def startup() -> None:
    """R02 loop + R03 init_http + R04 sync + load chat JSONL."""
    global _started
    if _started:
        return
    _ensure_loop()
    # configure_zeus_client()  # TODO: uncomment
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)

    from zeus_client import init_http, load_config

    # from my_package.chat_store import load_chats_from_jsonl

    run_coro(init_http())
    _sync_chat_requests_on_startup(run_coro(load_config()))
    # load_chats_from_jsonl()
    _started = True


def shutdown() -> None:
    if not _started:
        return
    from zeus_client import close_http

    try:
        run_coro(close_http(), timeout=10)
    except Exception:
        pass


atexit.register(shutdown)
