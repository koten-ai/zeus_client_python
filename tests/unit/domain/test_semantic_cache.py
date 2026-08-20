"""Pure semantic-cache inject / deny / policy (ZF-WISH-001)."""

from __future__ import annotations

from zeus_client.config.models import (
    SemanticCacheConfig,
    SemanticCachePrivacyConfig,
    SemanticCacheRecallConfig,
    SemanticCacheWriteConfig,
)
from zeus_client.domain.semantic_cache import (
    block_text_denied_reason,
    heading_for,
    normalize_block_type,
    prepare_write_text,
    render_semantic_memory_inject,
    should_recall,
    should_write_auto,
    ttl_seconds_from,
    upsert_semantic_memory_on_system,
)


def test_defaults_off() -> None:
    cfg = SemanticCacheConfig()
    assert cfg.enabled is False
    ok, reason = should_recall(cfg, "please find cheap nonstop flights")
    assert ok is False
    assert reason == "disabled"
    ok_w, reason_w = should_write_auto(cfg)
    assert ok_w is False
    assert reason_w == "disabled"


def test_should_recall_min_chars_and_mode() -> None:
    cfg = SemanticCacheConfig(
        enabled=True,
        recall=SemanticCacheRecallConfig(min_query_chars=12),
    )
    assert should_recall(cfg, "ok")[0] is False
    assert should_recall(cfg, "ok")[1] == "min_query_chars"
    assert should_recall(cfg, "cheap nonstop flights")[0] is True
    ok, reason = should_recall(cfg, "cheap nonstop flights", mode="direct")
    assert ok is False
    assert reason == "mode"


def test_should_write_auto_explicit_only_default() -> None:
    cfg = SemanticCacheConfig(enabled=True)
    ok, reason = should_write_auto(cfg)
    assert ok is False
    assert reason == "write_explicit_only"
    on = SemanticCacheConfig(
        enabled=True,
        write=SemanticCacheWriteConfig(write_explicit_only=False, write_user_message=True),
    )
    assert should_write_auto(on)[0] is True


def test_deny_secrets_system_g2() -> None:
    assert block_text_denied_reason("Authorization: Bearer abc.def") == "secrets"
    assert block_text_denied_reason("here is my api_key=sk-abc") == "secrets"
    assert block_text_denied_reason("## SCOPE BRIEF\nfull dump") == "system_dump"
    assert block_text_denied_reason("note wish_i_knew later") == "g2"
    custom = SemanticCacheConfig(
        privacy=SemanticCachePrivacyConfig(deny_regex=(r"ssn:\s*\d+",)),
    )
    assert block_text_denied_reason("ssn: 123456789", custom) == "deny_regex"
    assert block_text_denied_reason("User prefers nonstop flights under 6h") is None


def test_prepare_write_text_min_and_truncate() -> None:
    cfg = SemanticCacheConfig(
        enabled=True,
        write=SemanticCacheWriteConfig(min_chars=24, max_chars_per_block=30),
    )
    payload, reason = prepare_write_text("short", cfg)
    assert payload is None
    assert reason == "min_chars"
    payload, reason = prepare_write_text("User prefers nonstop flights under 6h always", cfg)
    assert reason == ""
    assert payload is not None
    assert len(payload) == 30


def test_render_inject_score_desc_and_caps() -> None:
    blocks = [
        {"type": "conversational", "text": "low", "summary": "low hit", "score": 0.1},
        {"type": "profile", "text": "prefers nonstop", "summary": "short nonstop", "score": 0.9},
        {"type": "semantic", "text": "extra", "score": 0.5},
    ]
    out = render_semantic_memory_inject(
        blocks, max_chars=4000, max_blocks=2, include_fields=("summary", "text")
    )
    assert out.startswith("semantic_memory:")
    lines = out.splitlines()
    assert lines[1].startswith("1. [profile] short nonstop")
    assert "2. [semantic]" in lines[2]
    tiny = render_semantic_memory_inject(blocks, max_chars=40, max_blocks=5)
    assert tiny.startswith("semantic_memory:")
    assert len(tiny) <= 41  # heading + newline + maybe ellipsis
    assert render_semantic_memory_inject([], max_chars=100) == ""


def test_upsert_replaces_previous_block() -> None:
    msgs = [{"role": "system", "content": "You are helpful."}]
    upsert_semantic_memory_on_system(msgs, "semantic_memory:\n1. [profile] a")
    assert "semantic_memory:" in msgs[0]["content"]
    upsert_semantic_memory_on_system(msgs, "semantic_memory:\n1. [profile] b")
    assert msgs[0]["content"].count("semantic_memory:") == 1
    assert "[profile] b" in msgs[0]["content"]
    assert "[profile] a" not in msgs[0]["content"]
    user = {"role": "user", "content": "hi"}
    msgs.append(user)
    upsert_semantic_memory_on_system(msgs, "semantic_memory:\n1. [profile] c")
    assert user["content"] == "hi"


def test_helpers() -> None:
    assert heading_for(None) == "semantic_memory:"
    assert normalize_block_type("PROFILE") == "profile"
    assert normalize_block_type("nope") == "conversational"
    assert ttl_seconds_from(None) == 604800
    assert ttl_seconds_from({"profile": 10, "conversational": 99}) == 99
    assert ttl_seconds_from("120") == 120
