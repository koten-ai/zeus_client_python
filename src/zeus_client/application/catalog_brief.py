"""Optional live SCOPE BRIEF borrow (hash-excluded; V1 load_chat_request).

On-disk / bundled catalogs carry locked rules + verbs. Per-scope
``## SCOPE BRIEF`` / ``## MINI-SCHEMA`` is fetched from Zeus
``GET /v1/ai/chat_request.json`` and spliced after the locked prefix.
Fetch is best-effort: missing remote or transport errors leave the
disk catalog unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from zeus_client.domain.catalog import extract_scope_brief, merge_scope_brief

__all__ = ["ScopeBriefResult", "ensure_scope_brief", "live_mode_candidates"]

FetchFn = Callable[[str, str, str], Awaitable[Mapping[str, Any]]]

# Zeus /v1/ai/chat_request.json keys (not Catalog listing stems).
_KNOWN_LIVE_MODES = (
    "analytics",
    "auto",
    "code",
    "custom",
    "fraud",
    "open",
    "private",
    "prototype",
    "regulated",
    "research",
    "tenant",
)
_SKIP_V2_FAMILY = frozenset({"", "mode", "chat_request", "default"})


def _mode_from_catalog(chat_req: Mapping[str, Any] | None) -> str | None:
    if not isinstance(chat_req, Mapping):
        return None
    for key in ("_lineage", "_base_meta"):
        raw = chat_req.get(key)
        if not isinstance(raw, Mapping):
            continue
        m = raw.get("mode")
        if isinstance(m, str) and m.strip():
            return m.strip()
    return None


def live_mode_candidates(mode: str, *, lineage_mode: str | None = None) -> tuple[str, ...]:
    """Modes to try for ``/v1/ai/chat_request.json``.

    Disk catalogs may be named ``analytics_v2_base_6``; Zeus live usually
    keys the brief as ``analytics``. Stem-named files such as
    ``mode_v2_base-6.1_analytics_stamped`` must not yield family ``mode``.
    """
    m = (mode or "analytics").strip() or "analytics"
    out: list[str] = []

    def add(name: str | None) -> None:
        n = (name or "").strip()
        if n and n not in out:
            out.append(n)

    add(m)
    add(lineage_mode)
    if "_v2_" in m:
        family = m.split("_v2_", 1)[0].strip()
        if family not in _SKIP_V2_FAMILY:
            add(family)
    for token in m.split("_"):
        if token in _KNOWN_LIVE_MODES:
            add(token)
    add("analytics")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class ScopeBriefResult:
    body: dict[str, Any]
    note: str
    merged: bool
    req_id: str = ""


async def ensure_scope_brief(
    chat_req: Mapping[str, Any] | None,
    *,
    fetch: FetchFn | None,
    bucket: str,
    scope: str,
    mode: str,
    req_id: str = "",
) -> ScopeBriefResult:
    """Merge a live brief when the catalog has none. Never raises."""
    body = dict(chat_req) if isinstance(chat_req, Mapping) else {}
    if extract_scope_brief(body):
        return ScopeBriefResult(body=body, note="scope_brief: already present", merged=False)
    if fetch is None:
        return ScopeBriefResult(
            body=body,
            note="scope_brief: live fetch skipped (no catalog_remote)",
            merged=False,
        )
    last_err = ""
    saw_empty = False
    for candidate in live_mode_candidates(mode, lineage_mode=_mode_from_catalog(body)):
        try:
            live = await fetch(bucket, scope, candidate)
        except Exception as exc:  # noqa: BLE001 — optional network
            last_err = str(exc)
            continue
        live_doc = dict(live) if isinstance(live, Mapping) else {}
        brief = extract_scope_brief(live_doc)
        if brief:
            note = "scope_brief: live merge"
            if candidate != (mode or "").strip():
                note = f"scope_brief: live merge (mode={candidate})"
            return ScopeBriefResult(
                body=merge_scope_brief(body, brief),
                note=note,
                merged=True,
                req_id=req_id,
            )
        saw_empty = True
    if last_err and not saw_empty:
        return ScopeBriefResult(
            body=body,
            note=f"scope_brief: live fetch failed: {last_err}",
            merged=False,
        )
    return ScopeBriefResult(
        body=body,
        note="scope_brief: live response had no SCOPE BRIEF",
        merged=False,
        req_id=req_id,
    )
