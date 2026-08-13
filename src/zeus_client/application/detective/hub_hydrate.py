"""Optional Hub hydrate (links-only default; soft-fail)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["merge_hub_hydrate"]


def merge_hub_hydrate(
    briefing: Mapping[str, Any],
    hub_payload: Mapping[str, Any] | None,
    *,
    preferred_req_id: str | None = None,
) -> dict[str, Any]:
    """Attach hub snapshot metadata without clobbering client inject **pass**.

    Full network fetch is left to adapters; this only merges an already-fetched
    payload. Client prompt verdict is authoritative for external inject.
    """
    out = dict(briefing)
    if not isinstance(hub_payload, Mapping) or not hub_payload:
        out["hub_hydrated"] = False
        return out

    out["hub_hydrated"] = True
    out["source"] = "client+hub"
    hub_meta: dict[str, Any] = {
        "preferred_req_id": preferred_req_id,
        "keys": sorted(str(k) for k in hub_payload.keys()),
    }
    hub_pc = hub_payload.get("prompt_checklist")
    client_prompt = out.get("prompt") if isinstance(out.get("prompt"), Mapping) else {}
    client_verdict = str(client_prompt.get("verdict") or "")
    notes = list(client_prompt.get("notes") or []) if isinstance(client_prompt, Mapping) else []

    if isinstance(hub_pc, Mapping):
        hub_verdict = str(hub_pc.get("verdict") or hub_pc.get("status") or "")
        hub_meta["prompt_checklist_verdict"] = hub_verdict
        # Do not overwrite client inject pass with tool-hop fail
        if client_verdict == "pass" and hub_verdict in ("fail", "skip", "missing"):
            notes.append(
                "hub_prompt_conflict: client inject pass; hub tool-hop checklist "
                f"={hub_verdict} (client remains authoritative)"
            )
            prompt = dict(client_prompt)
            prompt["notes"] = notes
            out["prompt"] = prompt
    out["hub"] = hub_meta
    return out
