"""V1-shaped shims over ZeusRuntime (Phase 8). Time-boxed ≤1 minor after cutover.

Prefer::

    async with ZeusRuntime.from_config() as rt:
        result = await rt.agent.run_turn(...)
        hits = await rt.data.search(...)
        verb = await rt.data.find(...)

These free functions emit :class:`DeprecationWarning` and require an explicit
``runtime=`` (V2 does not recreate process-global HTTP from free kwargs).
"""

from __future__ import annotations

from zeus_client_v2.compat.v1.run_agent import run_agent, turn_result_as_v1_tuple
from zeus_client_v2.compat.v1.run_search import run_search
from zeus_client_v2.compat.v1.run_verb import run_find, run_verb

__all__ = [
    "run_agent",
    "run_search",
    "run_verb",
    "run_find",
    "turn_result_as_v1_tuple",
]
