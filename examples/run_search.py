"""Minimal typeahead via rt.data.search (2.0+)."""

from __future__ import annotations

import asyncio

from zeus_client import SuggestOptions, ZeusRuntime
from zeus_client.adapters.catalog_fs.store import FsCatalogStore
from zeus_client.adapters.secrets_env.store import EnvSecretStore
from zeus_client.adapters.zeus_http import HttpxZeusPort
from zeus_client.config.loader import load_runtime_config


async def main() -> None:
    cfg = load_runtime_config("config.json", profile="development")
    secrets = EnvSecretStore()
    catalog = FsCatalogStore(root=cfg.chat_requests_dir or "data/chat_requests")
    async with ZeusRuntime(cfg, secrets=secrets, catalog=catalog) as rt:
        rt.services.zeus = HttpxZeusPort(
            endpoint=rt.config.zeus, secrets=secrets, journal=rt.journal
        )
        sug = await rt.data.search("sushi", options=SuggestOptions(limit=8))
        print(sug.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
