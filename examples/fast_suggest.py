#!/usr/bin/env python3
"""Fast-tier typeahead suggest (no LLM) against yelp-data.

Usage (with Zeus up and config.json pointing at it)::

    python examples/fast_suggest.py "sushi"
    python examples/fast_suggest.py "Pathmark"

Debounce this in your UI; use ``run_agent`` only on full submit.
"""
from __future__ import annotations

import asyncio
import json
import sys

from zeus_client import ZeusClient, load_config, run_fast_suggest_from_config
from zeus_client.zeus.suggest import SuggestOptions


async def main(query: str) -> int:
    async with ZeusClient():
        cfg = await load_config()
        result = await run_fast_suggest_from_config(
            query,
            cfg,
            options=SuggestOptions(limit=8, fts_timeout_ms=2000),
        )
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0 if not result.error else 1


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or "sushi"
    raise SystemExit(asyncio.run(main(q)))
