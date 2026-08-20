"""Hash-stable control-plane inject oracles (ZCP-13 · Task 4.3).

Port of tests/test_prompt_inject_hash_stable.py — inject only after
## SCOPE BRIEF / ## MINI-SCHEMA so contract_hash is unchanged.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from zeus_client.application.control_plane_inject import (
    InjectSettings,
    apply_control_plane_inject,
    prepare_inject_settings,
    prepare_settings,
)
from zeus_client.config.models import ClientSettings
from zeus_client.domain.contract import compute_contract_hash


def _catalog_with_brief() -> dict:
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful agent.\n\n"
                    "## SCOPE BRIEF\n"
                    "bucket=beer scope=_default\n\n"
                    "## MINI-SCHEMA\n"
                    "Beer: name, abv\n"
                ),
            }
        ],
        "verbs": [{"function": {"name": "find", "parameters": {}}}],
        "contract": {"hash": "md5:placeholder"},
    }


def test_inject_keeps_contract_hash_stable() -> None:
    chat = _catalog_with_brief()
    before = compute_contract_hash(chat)
    settings = prepare_inject_settings(
        {
            "company_context": "We are a craft beer marketplace.",
            "rules": {"seasonal": "Prefer seasonal beers when asked."},
            "output_request": {
                "app": {
                    "fields": {
                        "offer_code": {
                            "type": "string",
                            "description": "Promo if any",
                        },
                    }
                },
            },
            "locale": "en-US",
            "channel": "web",
        }
    )
    after_doc = apply_control_plane_inject(chat, settings)
    after = compute_contract_hash(after_doc)
    assert before == after
    content = after_doc["messages"][0]["content"]
    assert "## Company context" in content
    assert "## Rules" in content
    assert "seasonal" in content
    assert "## Output request" in content
    assert "offer_code" in content
    assert "## Session settings" in content
    assert "locale=en-US" in content


def test_inject_noop_without_brief_marker() -> None:
    chat = {
        "messages": [{"role": "system", "content": "plain system only"}],
    }
    settings = prepare_inject_settings({"company_context": "Brand X"})
    out = apply_control_plane_inject(chat, settings)
    assert out["messages"][0]["content"] == "plain system only"
    assert compute_contract_hash(out) == compute_contract_hash(chat)


def test_inject_also_splices_instructions_system_prompt() -> None:
    chat = {
        "messages": [
            {
                "role": "system",
                "content": "base\n\n## SCOPE BRIEF\nscope x",
            }
        ],
        "instructions": {
            "system_prompt": "instr base\n\n## MINI-SCHEMA\nfields",
        },
    }
    h0 = compute_contract_hash(chat)
    settings = prepare_inject_settings({"company_context": "Acme Corp"})
    out = apply_control_plane_inject(chat, settings)
    assert compute_contract_hash(out) == h0
    assert "## Company context" in out["messages"][0]["content"]
    assert "## Company context" in out["instructions"]["system_prompt"]


def test_inject_idempotent_second_pass() -> None:
    chat = _catalog_with_brief()
    settings = prepare_inject_settings({"company_context": "Once only brand"})
    once = apply_control_plane_inject(chat, settings)
    twice = apply_control_plane_inject(once, settings)
    assert once["messages"][0]["content"] == twice["messages"][0]["content"]
    assert once["messages"][0]["content"].count("## Company context") == 1


def test_inject_empty_settings_returns_same_object() -> None:
    chat = _catalog_with_brief()
    settings = InjectSettings()
    out = apply_control_plane_inject(chat, settings)
    assert out is chat


def test_prepare_settings_accepts_alias_shaped_client_settings() -> None:
    """BFF may import ClientSettings via zeus_client_v2 — do not require identity."""

    class _AliasSettings:
        output_request = None
        company_context = None
        rules = None
        tenant_rules = None
        override_defaults = False
        ruleset_id = None

        def with_updates(self, **kwargs):  # noqa: ANN003
            for k, v in kwargs.items():
                setattr(self, k, v)
            return self

    out = prepare_settings(_AliasSettings())
    assert out.output_request is None
    assert isinstance(out.rules, dict)
    assert ClientSettings().ai_process_result is False


def test_prepare_rejects_type_only_output_field() -> None:
    with pytest.raises(ValueError, match="description"):
        prepare_inject_settings(
            {
                "output_request": {
                    "app": {"fields": {"x": {"type": "string"}}},
                }
            }
        )


def test_company_context_hard_truncate() -> None:
    words = " ".join(f"w{i}" for i in range(300))
    s = prepare_inject_settings({"company_context": words})
    assert len(s.company_context.split()) == 250  # type: ignore[union-attr]


def test_original_catalog_not_mutated() -> None:
    chat = _catalog_with_brief()
    original = deepcopy(chat)
    settings = prepare_inject_settings({"company_context": "Brand"})
    apply_control_plane_inject(chat, settings)
    assert chat == original
