"""Support pack markdown for tickets (G2-safe — not chat UI)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["build_support_pack"]


def build_support_pack(
    *,
    headline: str,
    turn_id: str = "",
    preferred_req_id: str | None = None,
    req_ids: Sequence[str] | None = None,
    playbooks: Sequence[Mapping[str, Any]] | None = None,
    prompt_verdict: str = "",
    notes: Sequence[str] | None = None,
    status: str = "",
) -> dict[str, Any]:
    lines = [
        f"# Detective support pack",
        "",
        f"**Headline:** {headline}",
        f"**Turn:** `{turn_id or '-'}`",
        f"**Status:** `{status or '-'}`",
        f"**Prompt verdict:** `{prompt_verdict or '-'}`",
        f"**Preferred req_id:** `{preferred_req_id or '-'}`",
        f"**Req ids:** {', '.join(f'`{r}`' for r in (req_ids or ())) or '-'}",
        "",
        "## Playbooks",
    ]
    pbs = list(playbooks or ())
    if not pbs:
        lines.append("- (none fired)")
    else:
        for p in pbs:
            if not isinstance(p, Mapping):
                continue
            lines.append(
                f"- **{p.get('id')}** ({p.get('severity')}): {p.get('summary')}"
            )
    if notes:
        lines.extend(["", "## Notes (truncated)"])
        for n in list(notes)[:12]:
            lines.append(f"- {n}")
    md = "\n".join(lines) + "\n"
    return {
        "headline": headline,
        "markdown": md,
        "preferred_req_id": preferred_req_id,
        "playbook_ids": [str(p.get("id")) for p in pbs if isinstance(p, Mapping)],
    }
