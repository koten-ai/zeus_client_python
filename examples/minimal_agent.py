"""Minimal ZeusRuntime agent example (2.0+)."""

from __future__ import annotations

import asyncio

from zeus_client import ClientSettings, ZeusRuntime
from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.adapters.llm_openai_compatible import OpenAICompatibleLlmClient
from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http import HttpxZeusPort
from zeus_client.adapters.zeus_http.catalog_remote import HttpxCatalogRemote
from zeus_client.config.loader import load_runtime_config


async def main() -> None:
    cfg = load_runtime_config("config.json", profile="development")
    secrets = EnvSecretStore()
    catalog = FsCatalogStore(root=cfg.chat_requests_dir or "data/chat_requests")
    async with ZeusRuntime(cfg, secrets=secrets, catalog=catalog) as rt:
        rt.services.zeus = HttpxZeusPort(
            endpoint=rt.config.zeus, secrets=secrets, journal=rt.journal
        )
        rt.services.llm = OpenAICompatibleLlmClient(
            config=rt.config.llm, secrets=secrets, journal=rt.journal
        )
        rt.services.catalog_remote = HttpxCatalogRemote(  # type: ignore[attr-defined]
            endpoint=rt.config.zeus, secrets=secrets
        )
        loaded = await rt.catalog.load(mode=rt.config.settings.mode)
        result = await rt.agent.run_turn(
            "How many breweries are in the dataset?",
            settings=ClientSettings(ai_process_result=False),
            chat_request=dict(loaded.body),
        )
        print("Answer:", result.answer)
        print("Status:", result.status)


if __name__ == "__main__":
    asyncio.run(main())
