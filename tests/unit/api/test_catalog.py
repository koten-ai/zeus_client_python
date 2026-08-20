"""CatalogAPI load / info / contract / mini_schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures.catalog_brief import base_chat_req

from zeus_client.config.models import DataTarget, RuntimeConfig
from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.runtime import ZeusRuntime

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "base-5.3"


@pytest.mark.asyncio
async def test_load_info_and_pack_schema() -> None:
    cfg = RuntimeConfig(
        chat_requests_dir=str(FIX),
        target=DataTarget(bucket="x", scope="_default"),
        client_floor="client-floor-5",
    )
    async with ZeusRuntime(cfg) as rt:
        loaded = await rt.catalog.load("analytics", base_id="base-5.3")
        assert loaded.base_id == "base-5.3"
        assert loaded.response_output_schema is not None
        assert isinstance(loaded.response_output_example, dict)
        assert loaded.response_output_example.get("summary")
        info = await rt.catalog.info("analytics", base_id="base-5.3")
        assert info["stamp_present"] == "true"
        assert info["has_response_schema"] == "true"
        assert info["client_floor"] == "client-floor-5"
        bound = rt.catalog.contract.bind("x", "_default", "analytics", loaded.body)
        assert bound["hash_source"] == "stamp"
        assert bound["contract_hash"].startswith("md5:")
        mini = rt.catalog.mini_schema.from_catalog(loaded.body)
        assert mini["source"] == "disk"


@pytest.mark.asyncio
async def test_contract_bind_never_invents() -> None:
    cfg = RuntimeConfig(chat_requests_dir=str(FIX), client_floor="client-floor-5")
    async with ZeusRuntime(cfg) as rt:
        with pytest.raises(CatalogError) as ei:
            rt.catalog.contract.bind("nope", "_default", "analytics", {"messages": []})
        assert ei.value.code == ErrorCode.CONTRACT_HASH_MISSING
        with pytest.raises(CatalogError) as ei2:
            rt.catalog.contract.hash({"messages": []})
        assert ei2.value.code == ErrorCode.CONTRACT_HASH_MISSING


@pytest.mark.asyncio
async def test_floor_blocks_higher_pack(tmp_path: Path) -> None:
    import json

    p = tmp_path / "chat_request_analytics_base-6.1.json"
    p.write_text(
        json.dumps(
            {
                "_lineage": {"base_id": "base-6.1"},
                "messages": [{"role": "system", "content": "x"}],
                "contract": {"hash": "md5:deadbeef"},
            }
        ),
        encoding="utf-8",
    )
    cfg = RuntimeConfig(
        chat_requests_dir=str(tmp_path),
        target=DataTarget(bucket="x", scope="_default"),
        client_floor="client-floor-5",
    )
    async with ZeusRuntime(cfg) as rt:
        with pytest.raises(CatalogError) as ei:
            await rt.catalog.load("analytics", base_id="base-6.1")
        assert ei.value.code == ErrorCode.PRECONDITION_FAILED


PIN = Path(__file__).resolve().parents[2] / "fixtures" / "pin-base-1"


@pytest.mark.asyncio
async def test_pin_path_load_and_bind() -> None:
    cfg = RuntimeConfig(
        chat_requests_dir=str(PIN),
        target=DataTarget(bucket="x", scope="_default"),
        client_floor="client-floor-5",
        production_base_id="base-1",
    )
    async with ZeusRuntime(cfg) as rt:
        loaded = await rt.catalog.load_pin("analytics")
        assert loaded.base_id == "base-1"
        assert loaded.lineage_id == "base-1"
        assert loaded.contract_hash
        bound = rt.catalog.contract.bind("x", "_default", "analytics", loaded.body)
        assert bound["hash_source"] == "stamp"
        stripped = dict(loaded.body)
        stripped.pop("contract", None)
        stripped.pop("_hash", None)
        stripped.pop("hash", None)
        with pytest.raises(CatalogError) as ei:
            rt.catalog.contract.bind("x", "_default", "analytics", stripped)
        assert ei.value.code == ErrorCode.CONTRACT_HASH_MISSING


@pytest.mark.asyncio
async def test_load_pin_requires_configured_id() -> None:
    cfg = RuntimeConfig(chat_requests_dir=str(PIN), production_base_id=None)
    async with ZeusRuntime(cfg) as rt:
        with pytest.raises(CatalogError) as ei:
            await rt.catalog.load_pin("analytics")
        assert ei.value.code == ErrorCode.CATALOG_NOT_FOUND


class _FakeCatalogRemote:
    def __init__(self, body: dict, req_id: str = "req-live-1") -> None:
        self._body = body
        self.last_req_id = req_id
        self.calls = 0

    async def fetch_chat_request(
        self, bucket: str, scope: str, mode: str, **kwargs: object
    ) -> dict:
        self.calls += 1
        return self._body


class _BoomRemote:
    last_req_id = ""

    async def fetch_chat_request(self, *args: object, **kwargs: object) -> dict:
        raise RuntimeError("live down")


@pytest.mark.asyncio
async def test_mini_schema_get_live_and_disk_fallback() -> None:
    cfg = RuntimeConfig(
        chat_requests_dir=str(FIX),
        target=DataTarget(bucket="x", scope="_default"),
        client_floor="client-floor-5",
    )
    async with ZeusRuntime(cfg) as rt:
        rt.services.catalog_remote = _FakeCatalogRemote(base_chat_req(), "req-live-9")
        live = await rt.catalog.mini_schema.get(live=True)
        assert live["source"] == "live"
        assert live["req_id"] == "req-live-9"
        assert "Beer" in live["entity_types"]

        rt.services.catalog_remote = _BoomRemote()
        disk = await rt.catalog.mini_schema.get("analytics", live=True, base_id="base-5.3")
        assert disk["source"] == "disk"


@pytest.mark.asyncio
async def test_load_for_turn_merges_live_brief(tmp_path: Path) -> None:
    import json

    disk = {
        "messages": [{"role": "system", "content": "LOCKED RULES"}],
        "verbs": [{"function": {"name": "find"}}],
    }
    (tmp_path / "chat_request_analytics_v2.json").write_text(json.dumps(disk), encoding="utf-8")
    live = base_chat_req()
    cfg = RuntimeConfig(
        chat_requests_dir=str(tmp_path),
        target=DataTarget(bucket="travel-sample", scope="_default"),
        client_floor="client-floor-5",
    )
    async with ZeusRuntime(cfg) as rt:
        remote = _FakeCatalogRemote(live, "req-brief-1")
        rt.services.catalog_remote = remote
        loaded = await rt.catalog.load_for_turn("analytics")
        content = loaded.body["messages"][0]["content"]
        assert content.startswith("LOCKED RULES")
        assert "## SCOPE BRIEF" in content
        assert "## MINI-SCHEMA" in content
        assert "live scope brief" in loaded.source
        assert remote.calls == 1

        # Disk stamp is unchanged — each load_for_turn re-borrows.
        again = await rt.catalog.ensure_scope_brief(loaded.body)
        assert again.merged is False
        assert again.note == "scope_brief: already present"
        assert remote.calls == 1


@pytest.mark.asyncio
async def test_load_for_turn_survives_dead_remote(tmp_path: Path) -> None:
    import json

    disk = {"messages": [{"role": "system", "content": "LOCKED RULES"}]}
    (tmp_path / "chat_request_analytics_v2.json").write_text(json.dumps(disk), encoding="utf-8")
    cfg = RuntimeConfig(
        chat_requests_dir=str(tmp_path),
        target=DataTarget(bucket="x", scope="_default"),
        client_floor="client-floor-5",
    )
    async with ZeusRuntime(cfg) as rt:
        rt.services.catalog_remote = _BoomRemote()
        loaded = await rt.catalog.load_for_turn("analytics")
        assert loaded.body["messages"][0]["content"] == "LOCKED RULES"
        assert "live fetch failed" in loaded.source
