"""Agent-memory use-case helpers — policy + inject around AgentMemoryPort."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zeus_client.config.models import DataTarget, SemanticCacheConfig
from zeus_client.domain.semantic_cache import (
    normalize_block_type,
    prepare_write_text,
    render_semantic_memory_inject,
    should_recall,
    should_write_auto,
    upsert_semantic_memory_on_system,
)
from zeus_client.observability.metrics import MetricsPort, NullMetrics
from zeus_client.ports.agent_memory import (
    AgentMemoryPort,
    AgentMemoryStatus,
    RecallResult,
    WriteResult,
)

__all__ = [
    "isolation_user_id",
    "skipped_recall",
    "skipped_write",
    "hop_from_memory",
    "recall_and_inject",
    "write_memory_block",
    "local_disabled_status",
]


def isolation_user_id(cfg: SemanticCacheConfig, auth_mode: str) -> str | None:
    """Body user_id only for lab ``auth_mode=none``. Production uses Zeus principal."""
    if (auth_mode or "").strip().lower() != "none":
        return None
    uid = (cfg.dev_user_id or "").strip()
    return uid or None


def skipped_recall(reason: str) -> RecallResult:
    return RecallResult(
        ok=False,
        status_code=0,
        skipped=True,
        skip_reason=reason,
    )


def skipped_write(reason: str) -> WriteResult:
    return WriteResult(
        ok=False,
        status_code=0,
        skipped=True,
        skip_reason=reason,
    )


def local_disabled_status() -> AgentMemoryStatus:
    return AgentMemoryStatus(enabled=False, error="disabled")


def hop_from_memory(
    *,
    name: str,
    result: RecallResult | WriteResult,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "req_id": result.req_id,
        "name": name,
        "path_class": "agent_memory",
        "status": result.status_code,
        "ok": bool(result.ok),
        "url": result.url,
        "error": result.error,
        "snippet": "",
    }
    if duration_ms is not None:
        rec["ms"] = duration_ms
    elif isinstance(result, RecallResult) and result.latency_ms:
        rec["ms"] = result.latency_ms
    return {k: v for k, v in rec.items() if v is not None and v != ""}


def _metric(
    metrics: MetricsPort | None,
    op: str,
    result: str,
    duration_ms: int | None = None,
) -> None:
    m = metrics or NullMetrics()
    m.incr("zeus_client_agent_memory_total", labels={"op": op, "result": result})
    if duration_ms is not None:
        m.observe(
            "zeus_client_agent_memory_seconds",
            float(duration_ms) / 1000.0,
            labels={"op": op},
        )


async def recall_and_inject(
    port: AgentMemoryPort | None,
    cfg: SemanticCacheConfig,
    messages: list[dict[str, Any]],
    query: str,
    *,
    mode: str = "agent",
    headers: Mapping[str, str] | None = None,
    user_id: str | None = None,
    target: DataTarget | None = None,
    metrics: MetricsPort | None = None,
    probe_available: bool | None = None,
) -> tuple[RecallResult, str]:
    """Recall then splice bag B. Returns (result, snippet). Never raises."""
    ok, reason = should_recall(cfg, query, mode=mode)
    if not ok:
        _metric(metrics, "recall", "skipped")
        return skipped_recall(reason), ""
    if port is None:
        _metric(metrics, "recall", "skipped")
        return skipped_recall("no_port"), ""
    if probe_available is False:
        _metric(metrics, "recall", "skipped")
        return skipped_recall("unavailable"), ""
    rec = cfg.recall
    result = await port.recall(
        query,
        top_k=rec.top_k,
        types=rec.types,
        min_score=rec.min_score,
        timeout_ms=rec.timeout_ms,
        headers=headers,
        user_id=user_id,
        bucket=target.bucket if target else None,
        scope=target.scope if target else None,
    )
    if result.skipped:
        _metric(metrics, "recall", "skipped")
        return result, ""
    if not result.ok:
        _metric(
            metrics,
            "recall",
            "timeout" if result.skip_reason == "timeout" or result.error == "timeout" else "error",
            result.latency_ms,
        )
        return result, ""
    inj = cfg.inject
    snippet = render_semantic_memory_inject(
        result.block_maps(),
        key=inj.key,
        max_chars=inj.max_chars,
        max_blocks=inj.max_blocks,
        include_fields=inj.include_fields,
        order=inj.order,
    )
    if snippet:
        upsert_semantic_memory_on_system(messages, snippet, key=inj.key)
    _metric(metrics, "recall", "ok", result.latency_ms)
    return result, snippet


async def write_memory_block(
    port: AgentMemoryPort | None,
    cfg: SemanticCacheConfig,
    text: str,
    *,
    mode: str = "agent",
    block_type: str | None = None,
    summary: str | None = None,
    headers: Mapping[str, str] | None = None,
    user_id: str | None = None,
    zeus_session_id: str | None = None,
    target: DataTarget | None = None,
    metrics: MetricsPort | None = None,
    explicit: bool = True,
    probe_available: bool | None = None,
) -> WriteResult:
    """Write one block. Never raises. Explicit API ignores write_explicit_only."""
    if not cfg.enabled:
        _metric(metrics, "write", "skipped")
        return skipped_write("disabled")
    if mode and mode not in {str(m).lower() for m in cfg.apply_to_modes}:
        _metric(metrics, "write", "skipped")
        return skipped_write("mode")
    if not cfg.write.enabled:
        _metric(metrics, "write", "skipped")
        return skipped_write("write_disabled")
    if not explicit:
        ok_auto, reason = should_write_auto(cfg, mode=mode)
        if not ok_auto:
            _metric(metrics, "write", "skipped")
            return skipped_write(reason)
    if port is None:
        _metric(metrics, "write", "skipped")
        return skipped_write("no_port")
    if probe_available is False:
        _metric(metrics, "write", "skipped")
        return skipped_write("unavailable")
    payload, deny = prepare_write_text(text, cfg)
    if payload is None:
        _metric(metrics, "write", "skipped")
        return skipped_write(deny or "denied")
    typ = normalize_block_type(block_type or cfg.write.default_type)
    if typ not in set(cfg.write.types_allowed):
        _metric(metrics, "write", "skipped")
        return skipped_write("type_not_allowed")
    use_summary = summary
    if cfg.embed.prefer_summary_for_write and use_summary:
        # Zeus still embeds; client may send shorter summary alongside text.
        pass
    result = await port.write_block(
        payload,
        type=typ,
        summary=use_summary,
        ttl_seconds=cfg.write.ttl_seconds,
        headers=headers,
        user_id=user_id,
        zeus_session_id=zeus_session_id,
        bucket=target.bucket if target else None,
        scope=target.scope if target else None,
    )
    if result.skipped:
        _metric(metrics, "write", "skipped")
        return result
    _metric(
        metrics,
        "write",
        "ok" if result.ok else ("timeout" if result.error == "timeout" else "error"),
    )
    return result
