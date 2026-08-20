"""Later-wins LLM role resolve (ZCP-68)."""

from __future__ import annotations

from zeus_client.config.models import JobsConfig, LlmProviderConfig, LlmRoleConfig
from zeus_client.domain.llm_roles import LlmRole, resolve_llm_slice


def test_worker_inherits_default_then_role_then_unit() -> None:
    base = LlmProviderConfig(
        model="fast-worker",
        api_key_env="LLM_DEFAULT_KEY",
        roles={
            "worker": LlmRoleConfig(model="fast-worker", api_key_env="LLM_WORKER_KEY"),
            "orchestrator": LlmRoleConfig(model="strong-planner", api_key_env="LLM_ORCH_KEY"),
        },
    )
    got = resolve_llm_slice(
        base,
        role=LlmRole.WORKER,
        jobs=JobsConfig(models={"worker": {"model": "fast-worker-v2"}}),
        job_models={"units": {"u1": {"model": "fast-worker-v3"}}},
        unit_llm={"temperature": 0.1},
        unit_id="u1",
    )
    assert got.model == "fast-worker-v3"
    assert got.api_key_env == "LLM_WORKER_KEY"
    assert got.temperature == 0.1
    assert got.role == "worker"
    pub = got.to_public_dict()
    assert set(pub) >= {"role", "model", "api_key_env"}
    assert "api_key" not in pub


def test_orchestrator_ignores_unit_llm() -> None:
    base = LlmProviderConfig(
        model="fast-worker",
        api_key_env="LLM_DEFAULT_KEY",
        roles={"orchestrator": LlmRoleConfig(model="strong-planner", api_key_env="LLM_ORCH_KEY")},
    )
    got = resolve_llm_slice(
        base,
        role=LlmRole.ORCHESTRATOR,
        unit_llm={"model": "should-not-win", "api_key_env": "LLM_UNIT_KEY"},
        unit_id="u1",
    )
    assert got.model == "strong-planner"
    assert got.api_key_env == "LLM_ORCH_KEY"
    assert got.role == "orchestrator"


def test_empty_roles_uses_default_llm() -> None:
    base = LlmProviderConfig(model="fast-worker", api_key_env="LLM_DEFAULT_KEY")
    got = resolve_llm_slice(base, role=LlmRole.WORKER)
    assert got.model == "fast-worker"
    assert got.api_key_env == "LLM_DEFAULT_KEY"
    assert got.role == "worker"
