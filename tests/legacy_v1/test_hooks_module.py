"""Module-level hook shims in zeus_client.agent.hooks."""
import pytest

from zeus_client.agent import hooks


@pytest.mark.asyncio
async def test_module_level_before_zeus_dispatch_passthrough():
    args = {"bucket": "beer-sample", "where": {"state": "CA"}}
    out = await hooks.before_zeus_dispatch("find_nodes", args, {"round": 1})
    assert out is args
    assert out["where"]["state"] == "CA"


@pytest.mark.asyncio
async def test_module_level_after_zeus_dispatch_passthrough():
    text = await hooks.after_zeus_dispatch(
        "find_nodes", {}, 200, '{"rows":[]}', {"round": 2},
    )
    assert text == '{"rows":[]}'