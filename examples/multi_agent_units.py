"""Offline units illustration — NOT a MATRIX demo.

FakeJobRuntime is sequential and has no planner LLM.
Do not claim multi_agent=demo from this file.
"""

from __future__ import annotations

import asyncio

from zeus_client import JobsConfig, RuntimeConfig, UnitConfig, UnitKind, ZeusRuntime
from zeus_client.adapters.jobs_fake import FakeJobRuntime
from zeus_client.config.models import DataTarget


async def main() -> None:
    cfg = RuntimeConfig(
        target=DataTarget(bucket="west", scope="s", collection="c"),
        jobs=JobsConfig(),
    )
    rt = ZeusRuntime(cfg)
    rt.services.jobs = FakeJobRuntime(rt)
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.ZEUS_DIRECT,
            goal="list east beers",
            zeus_url="http://127.0.0.1:8080",
            bucket="east",
            scope="sales",
            collection="_default",
            call={"verb": "find", "body": {"entity_type": "Beer"}},
        )
    ]
    print("offline example only — wire a Zeus port before run; see docs/V2/MULTI_AGENT.md")
    print("units:", [u.unit_id for u in units])
    await rt.aclose()


if __name__ == "__main__":
    asyncio.run(main())
