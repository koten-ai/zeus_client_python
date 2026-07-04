"""Minimal programmatic Zeus agent example."""
import asyncio

from zeus_client import (
    ZeusClient,
    load_config,
    resolve_llm_provider_config,
    resolve_zeus_config,
    run_agent,
)


async def main() -> None:
    async with ZeusClient():
        cfg = await load_config()
        zcfg = resolve_zeus_config(cfg)
        provider = resolve_llm_provider_config(cfg)
        sample_key = cfg.get("default_sample", "beer-sample")
        sample = cfg["samples"][sample_key]

        answer, trace, turns, meta = await run_agent(
            zcfg["url"],
            zcfg,
            provider["base_url"],
            provider["api_key"],
            provider["models"][0],
            cfg.get("default_api_version", "v2"),
            cfg.get("default_mode", "analytics"),
            sample["bucket"],
            sample["scope"],
            sample["collection"],
            "How many breweries are in the dataset?",
            prior_turns=[],
        )
        print("Answer:", answer)
        print("Trace rounds:", trace.get("rounds"))


if __name__ == "__main__":
    asyncio.run(main())