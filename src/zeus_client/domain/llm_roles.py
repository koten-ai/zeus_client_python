"""Later-wins LLM role resolve (family API_CONFIG §7.6)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from zeus_client.config.models import JobsConfig, LlmProviderConfig, LlmRoleConfig

__all__ = ["LlmRole", "ResolvedLlmSlice", "resolve_llm_slice"]


class LlmRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    ADVISOR = "advisor"
    WORKER = "worker"


@dataclass(frozen=True, slots=True)
class ResolvedLlmSlice:
    role: str
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    provider: str | None = None
    temperature: float | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "provider": self.provider,
            "temperature": self.temperature,
        }


def _merge_partial(dst: dict[str, Any], src: Mapping[str, Any] | None) -> None:
    if not src:
        return
    for key in ("model", "api_key_env", "base_url", "provider", "temperature"):
        if key in src and src[key] is not None:
            dst[key] = src[key]


def resolve_llm_slice(
    base: LlmProviderConfig,
    *,
    role: LlmRole | str = LlmRole.WORKER,
    jobs: JobsConfig | None = None,
    job_models: Mapping[str, Any] | None = None,
    unit_llm: Mapping[str, Any] | None = None,
    unit_id: str | None = None,
) -> ResolvedLlmSlice:
    """Later-wins: default → role → jobs.models.<role> → jobs.run.models → unit (workers)."""
    role_name = role.value if isinstance(role, LlmRole) else str(role)
    acc: dict[str, Any] = {
        "model": base.model,
        "api_key_env": base.api_key_env,
        "base_url": base.base_url,
        "provider": base.provider,
        "temperature": None,
    }
    role_cfg = base.roles.get(role_name)
    if isinstance(role_cfg, LlmRoleConfig):
        _merge_partial(
            acc,
            {
                "model": role_cfg.model,
                "api_key_env": role_cfg.api_key_env,
                "base_url": role_cfg.base_url,
                "provider": role_cfg.provider,
                "temperature": role_cfg.temperature,
            },
        )
    if jobs is not None:
        role_models = jobs.models.get(role_name)
        if isinstance(role_models, Mapping):
            _merge_partial(acc, role_models)
    if job_models:
        role_job = job_models.get(role_name)
        if isinstance(role_job, Mapping):
            _merge_partial(acc, role_job)
        units = job_models.get("units")
        if isinstance(units, Mapping) and unit_id and unit_id in units:
            unit_models = units[unit_id]
            if isinstance(unit_models, Mapping):
                _merge_partial(acc, unit_models)
    if role_name == LlmRole.WORKER.value:
        _merge_partial(acc, unit_llm)
    return ResolvedLlmSlice(role=role_name, **acc)
