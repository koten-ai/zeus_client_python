"""Mode 3 job / unit domain types + isolation (ZCP-67)."""

from __future__ import annotations

import pytest

from zeus_client.domain.errors import ErrorCode, JobError
from zeus_client.domain.jobs import (
    JobBudgets,
    JobEvent,
    UnitConfig,
    UnitKind,
    validate_unit_map,
)


def test_unit_config_requires_scope_triple_fields() -> None:
    u = UnitConfig(
        unit_id="u1",
        kind=UnitKind.AGENT_TURN,
        zeus_url="http://127.0.0.1:8080",
        bucket="beer-sample",
        scope="sales",
        collection="_default",
        goal="shortlist fruit beers",
        catalog_mode="analytics",
        base_id="base-5.3",
    )
    assert u.kind is UnitKind.AGENT_TURN
    d = u.to_public_dict()
    assert "password" not in str(d).lower()
    assert "api_key" not in d


def test_job_event_is_minified() -> None:
    ev = JobEvent(seq=1, type="job.started", job_id="j1", ts_ms=1, payload={"status": "accepted"})
    assert ev.unit_id is None
    assert "password" not in ev.to_public_dict()


def test_invalid_budget_is_130003() -> None:
    with pytest.raises(JobError) as ei:
        JobBudgets(max_workers=0).validate()
    assert ei.value.code is ErrorCode.JOBS_BUDGET_INVALID


def test_missing_scope_is_130002() -> None:
    units = [
        UnitConfig(unit_id="u1", kind=UnitKind.ZEUS_DIRECT, goal="x", zeus_url="http://z"),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.JOBS_INVALID_UNIT_MAP


def test_agent_missing_catalog_is_130011() -> None:
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.AGENT_TURN,
            goal="x",
            zeus_url="http://z",
            bucket="b",
            scope="s",
            collection="c",
        ),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.UNITS_CATALOG_MISSING


def test_shared_session_across_units_is_130013() -> None:
    shared = "sess_shared"
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.ZEUS_DIRECT,
            goal="a",
            zeus_url="http://z",
            bucket="b",
            scope="s",
            collection="c",
            share_session_id=shared,
        ),
        UnitConfig(
            unit_id="u2",
            kind=UnitKind.ZEUS_DIRECT,
            goal="b",
            zeus_url="http://z",
            bucket="b",
            scope="east",
            collection="c",
            share_session_id=shared,
        ),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.UNITS_ISOLATION


def test_duplicate_unit_id_is_130002() -> None:
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.ZEUS_DIRECT,
            goal="a",
            zeus_url="http://z",
            bucket="b",
            scope="s",
            collection="c",
        ),
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.ZEUS_DIRECT,
            goal="b",
            zeus_url="http://z",
            bucket="b",
            scope="east",
            collection="c",
        ),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.JOBS_INVALID_UNIT_MAP


def test_http_json_unit_is_not_implemented() -> None:
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.HTTP_JSON,
            goal="x",
            zeus_url="http://z",
            bucket="b",
            scope="s",
            collection="c",
        ),
    ]
    with pytest.raises(JobError) as ei:
        validate_unit_map(units)
    assert ei.value.code is ErrorCode.NOT_IMPLEMENTED


def test_valid_two_scope_direct_units_pass() -> None:
    units = [
        UnitConfig(
            unit_id="u1",
            kind=UnitKind.ZEUS_DIRECT,
            goal="a",
            zeus_url="http://z",
            bucket="b",
            scope="s",
            collection="c",
        ),
        UnitConfig(
            unit_id="u2",
            kind=UnitKind.AGENT_TURN,
            goal="b",
            zeus_url="http://z",
            bucket="b",
            scope="east",
            collection="c",
            catalog_mode="analytics",
        ),
    ]
    validate_unit_map(units)
