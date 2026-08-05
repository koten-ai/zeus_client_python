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
from zeus_client.trace.tool_order import (
    build_tool_order,
    build_v1_tool_order_from_chats,
    tool_names_from_step,
)

__all__ = [
    "TRACE_SNIPPET_MAX",
    "build_aggregate_trace_payload",
    "build_tool_order",
    "build_v1_tool_order_from_chats",
    "extract_pipeline_meta",
    "normalize_hop",
    "normalize_hops",
    "ordered_req_ids_for_trace_posts",
    "select_primary_hop",
    "select_primary_req_id",
    "tool_names_from_step",
]