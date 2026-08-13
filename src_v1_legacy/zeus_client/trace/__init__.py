"""Trace parsing and multi-hop session-trace helpers."""

from zeus_client.trace.session_hops import (
    TRACE_SNIPPET_MAX,
    build_aggregate_trace_payload,
    extract_pipeline_meta,
    normalize_hop,
    normalize_hops,
    ordered_req_ids_for_trace_posts,
    select_primary_hop,
    select_primary_req_id,
)
from zeus_client.trace.tokens import (
    attach_trace_tokens,
    normalize_usage,
    sum_provider_tokens,
    usage_from_ai_response,
)
from zeus_client.trace.tool_order import (
    build_tool_order,
    build_v1_tool_order_from_chats,
    tool_names_from_step,
)

__all__ = [
    "TRACE_SNIPPET_MAX",
    "attach_trace_tokens",
    "build_aggregate_trace_payload",
    "build_tool_order",
    "build_v1_tool_order_from_chats",
    "extract_pipeline_meta",
    "normalize_hop",
    "normalize_hops",
    "normalize_usage",
    "ordered_req_ids_for_trace_posts",
    "select_primary_hop",
    "select_primary_req_id",
    "sum_provider_tokens",
    "tool_names_from_step",
    "usage_from_ai_response",
]