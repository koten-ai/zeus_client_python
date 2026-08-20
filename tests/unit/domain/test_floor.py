"""Client floor vs BASE pack wire."""

from __future__ import annotations

import pytest

from zeus_client.domain.errors import CatalogError, ErrorCode
from zeus_client.domain.floor import (
    assert_floor_allows,
    floor_required_for_base_id,
)


def test_floor_required_mapping() -> None:
    assert floor_required_for_base_id("base-1") == "client-floor-1"
    assert floor_required_for_base_id("base-5.3") == "client-floor-5"
    assert floor_required_for_base_id("base-6.1") == "client-floor-6.1"
    assert floor_required_for_base_id("cus-3") == "client-floor-5"


def test_floor_fail_closed() -> None:
    with pytest.raises(CatalogError) as ei:
        assert_floor_allows(client_floor="client-floor-5", base_id="base-6.1")
    assert ei.value.code == ErrorCode.PRECONDITION_FAILED


def test_floor_degraded_logs_not_raise() -> None:
    assert_floor_allows(
        client_floor="client-floor-5",
        base_id="base-6.1",
        allow_degraded=True,
    )


def test_floor_5_allows_base_53() -> None:
    assert_floor_allows(client_floor="client-floor-5", base_id="base-5.3")
