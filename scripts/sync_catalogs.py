#!/usr/bin/env python3
"""Sync stamped chat_request catalogs from Zeus into the user catalog dir.

Usage (demo_travel_sample):
  set ZEUS_CLIENT_CONFIG_DIR=..\\demo_travel_sample
  python scripts/sync_catalogs.py

With force re-download:
  python scripts/sync_catalogs.py --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from zeus_client import close_http, init_http, load_config, sync_chat_requests
from zeus_client.contract_hash import extract_stamped_hash
from zeus_client.zeus.catalog import chat_request_path


async def _run(force: bool) -> int:
    await init_http()
    try:
        cfg = await load_config()
        result = await sync_chat_requests(cfg, force=force)
        print(json.dumps({
            "synced": result.synced,
            "skipped": result.skipped,
            "errors": result.errors,
            "manifest": str(result.manifest_path) if result.manifest_path else None,
        }, indent=2))

        zcfg = cfg.get("zeus") or {}
        sample = cfg.get("default_sample", "travel-sample")
        triple = (cfg.get("samples") or {}).get(sample) or {}
        bucket = triple.get("bucket", sample)
        scope = triple.get("scope", "_default")
        mode = cfg.get("default_mode", "travel_booking")

        path = chat_request_path("v2", mode, bucket, scope)
        if not path or not path.is_file():
            print(f"ERROR: no catalog for mode={mode} scope={bucket}/{scope}", file=sys.stderr)
            return 1

        doc = json.loads(path.read_text(encoding="utf-8"))
        stamped = extract_stamped_hash(doc)
        print(f"catalog: {path}")
        print(f"embedded hash: {stamped or 'MISSING'}")
        return 0 if stamped else 1
    finally:
        await close_http()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-download even if manifest hash unchanged")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.force)))


if __name__ == "__main__":
    main()