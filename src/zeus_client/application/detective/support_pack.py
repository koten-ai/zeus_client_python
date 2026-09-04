"""Support pack markdown for tickets (G2-safe — not chat UI)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["build_support_pack"]


def _inject_sha(inj: Mapping[str, Any], kind: str) -> str:
    """Read sha12 from legacy top-level keys or Hub nested sections."""
    nested_key = "scope_brief" if kind == "brief" else "mini_schema"
    nested = inj.get(nested_key)
    if isinstance(nested, Mapping) and nested.get("sha12"):
        return str(nested["sha12"])
    top = inj.get("brief_sha12" if kind == "brief" else "mini_sha12")
    return str(top) if top else "-"


def _hop_line(h: Mapping[str, Any]) -> str:
    name = h.get("name") or h.get("path_class") or "?"
    status = h.get("status")
    ms = h.get("ms")
    err = h.get("error")
    rid = h.get("req_id") or "-"
    bits = [f"`{name}`", f"status={status}", f"ms={ms}", f"req=`{rid}`"]
    if err:
        bits.append(f"error={str(err)[:200]}")
    return "- " + " · ".join(str(b) for b in bits)


def build_support_pack(
    *,
    headline: str,
    turn_id: str = "",
    chat_id: str = "",
    session_id: str = "",
    preferred_req_id: str | None = None,
    req_ids: Sequence[str] | None = None,
    hops: Sequence[Mapping[str, Any]] | None = None,
    playbooks: Sequence[Mapping[str, Any]] | None = None,
    prompt_verdict: str = "",
    notes: Sequence[str] | None = None,
    status: str = "",
    target: Mapping[str, Any] | None = None,
    zeus_url: str | None = None,
    client_version: str = "",
    catalog: Mapping[str, Any] | None = None,
    contract_status: str | None = None,
    inject: Mapping[str, Any] | None = None,
    layer_a: Mapping[str, Any] | None = None,
    tokens: Mapping[str, Any] | None = None,
    export_ref: str | None = None,
) -> dict[str, Any]:
    tgt = dict(target or {})
    cat = dict(catalog or {})
    inj = dict(inject or {})
    la = dict(layer_a or {}) if isinstance(layer_a, Mapping) else {}
    tok = dict(tokens or {}) if isinstance(tokens, Mapping) else {}
    hop_list = [h for h in (hops or ()) if isinstance(h, Mapping)]

    lines = [
        "# Detective support pack",
        "",
        f"**Headline:** {headline}",
        f"**Status:** `{status or '-'}`",
        f"**Prompt verdict:** `{prompt_verdict or '-'}`",
        "",
        "## 1. Ids",
        f"- chat_id: `{chat_id or '-'}`",
        f"- turn_id: `{turn_id or '-'}`",
        f"- session_id: `{session_id or '-'}`",
        "",
        "## 2. Hops",
        f"- preferred_req_id: `{preferred_req_id or '-'}`",
        f"- req_ids: {', '.join(f'`{r}`' for r in (req_ids or ())) or '-'}",
    ]
    if hop_list:
        lines.extend(_hop_line(h) for h in hop_list)
    else:
        lines.append("- (no hops)")

    lines.extend(
        [
            "",
            "## 3. Target",
            f"- zeus.url: `{zeus_url or '-'}`",
            f"- bucket/scope/collection: `{tgt.get('bucket') or '-'}` / `{tgt.get('scope') or '-'}` / `{tgt.get('collection') or '-'}`",
            f"- mode: `{tgt.get('mode') or '-'}`",
            f"- client_version: `{client_version or '-'}`",
            "",
            "## 4. Catalog / contract",
            f"- has_scope_brief: `{cat.get('has_scope_brief')}`",
            f"- has_mini_schema: `{cat.get('has_mini_schema')}`",
            f"- tools_count: `{cat.get('tools_count', '-')}`",
            f"- contract_status: `{contract_status or '-'}`",
            "",
            "## 5. Inject proof",
            f"- brief_sha12: `{_inject_sha(inj, 'brief')}`",
            f"- mini_sha12: `{_inject_sha(inj, 'mini')}`",
            "",
            "## 6. Hop errors / rows",
        ]
    )
    errs = [
        h
        for h in hop_list
        if h.get("ok") is False or (isinstance(h.get("status"), int) and h["status"] >= 400)
    ]
    if errs:
        lines.extend(_hop_line(h) for h in errs)
    else:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## 7. Layer A",
            f"- via: `{la.get('via') or '-'}`",
            f"- confidence: `{la.get('confidence') or '-'}`",
            f"- policy_action: `{la.get('policy_action') or '-'}`",
            f"- synthetic: `{la.get('synthetic')}`",
            "",
            "## 8. Tokens",
            f"- prompt/completion/total: `{tok.get('prompt', 0)}` / `{tok.get('completion', 0)}` / `{tok.get('total', 0)}`",
            f"- ok: `{tok.get('ok')}`",
            "",
            "## 9. Journal export",
            f"- export_ref: `{export_ref or turn_id or '-'}`",
            "",
            "## Playbooks",
        ]
    )
    pbs = list(playbooks or ())
    if not pbs:
        lines.append("- (none fired)")
    else:
        for p in pbs:
            if not isinstance(p, Mapping):
                continue
            lines.append(f"- **{p.get('id')}** ({p.get('severity')}): {p.get('summary')}")
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
        "export_ref": export_ref or turn_id or None,
    }
