"""Hash-excluded prompt inject zones for base-5 control plane.

Splices company_context, named rules{}, output_request, and settings meta
AFTER SCOPE BRIEF / MINI-SCHEMA markers so contract_hash stays stable
(same strip boundary as business_logic inject).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping, Optional

from zeus_client.agent.settings import (
    ClientSettings,
    truncate_company_context,
)

COMPANY_HEADING = "## Company context"
RULES_HEADING = "## Rules"
OUTPUT_REQUEST_HEADING = "## Output request"
SETTINGS_META_HEADING = "## Session settings"


def _has_brief_marker(text: str) -> bool:
    return "## SCOPE BRIEF" in text or "## MINI-SCHEMA" in text


def _splice_after_brief(text: str, block: str, heading_line: str) -> str:
    if not text or not block:
        return text
    if not _has_brief_marker(text):
        # Avoid hash drift: only splice when brief marker present
        return text
    if heading_line in text:
        return text
    return text.rstrip() + "\n\n" + block.strip() + "\n"


def render_company_context(text: str | None) -> tuple[str, list[str]]:
    body, warnings = truncate_company_context(text)
    if not body.strip():
        return "", warnings
    section = f"{COMPANY_HEADING}\n\n{body.strip()}"
    return section, warnings


def render_rules_block(rules: Mapping[str, str] | None) -> str:
    if not rules:
        return ""
    lines = [RULES_HEADING, ""]
    for rid in sorted(rules.keys()):
        lines.append(f"- ({rid}) {rules[rid]}")
    lines.append("")
    lines.append(
        "On terminate, set business_rules_triggers as a sparse object "
        "keyed by these rule ids (true if the rule applied this round; "
        "omit or false otherwise)."
    )
    return "\n".join(lines)


def render_output_request_block(output_request: Mapping | None) -> str:
    if not output_request:
        return ""
    app = output_request.get("app") if isinstance(output_request, dict) else None
    fields = app.get("fields") if isinstance(app, dict) else None
    if not isinstance(fields, dict) or not fields:
        return ""
    lines = [
        OUTPUT_REQUEST_HEADING,
        "",
        "When you terminate, fill app_output with values only (no essays).",
        "Fields:",
    ]
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        # descriptions drive model text; types are for Client validation
        desc = (spec.get("description") or "").strip()
        tname = spec.get("type") or "string"
        lines.append(f"- {name} ({tname}): {desc}")
    return "\n".join(lines)


def render_settings_meta(settings: ClientSettings) -> str:
    bits = []
    if settings.locale:
        bits.append(f"locale={settings.locale}")
    if settings.language:
        bits.append(f"language={settings.language}")
    if settings.timezone:
        bits.append(f"timezone={settings.timezone}")
    if settings.channel:
        bits.append(f"channel={settings.channel}")
    if settings.market:
        bits.append(f"market={settings.market}")
    if settings.deployment_id:
        bits.append(f"deployment_id={settings.deployment_id}")
    if settings.ruleset_id:
        bits.append(f"ruleset_id={settings.ruleset_id}")
    if not bits:
        return ""
    return f"{SETTINGS_META_HEADING}\n\n" + ", ".join(bits)


def build_inject_block(settings: ClientSettings) -> tuple[str, list[str]]:
    """Concatenate inject sections; returns (markdown, warnings)."""
    warnings: list[str] = []
    parts: list[str] = []
    company, cw = render_company_context(settings.company_context)
    warnings.extend(cw)
    if company:
        parts.append(company)
    meta = render_settings_meta(settings)
    if meta:
        parts.append(meta)
    rules = render_rules_block(settings.rules)
    if rules:
        parts.append(rules)
    out_req = render_output_request_block(settings.output_request)
    if out_req:
        parts.append(out_req)
    return "\n\n".join(parts), warnings


def apply_control_plane_inject(chat_req: dict, settings: ClientSettings) -> dict:
    """Deepcopy chat_req and splice inject block into system prompt(s)."""
    block, _warnings = build_inject_block(settings)
    if not block.strip():
        return chat_req
    # Use first heading in block for idempotency check
    heading_line = block.splitlines()[0]
    out = deepcopy(chat_req)

    def _splice(text: str) -> str:
        return _splice_after_brief(text or "", block, heading_line)

    messages = out.get("messages") or []
    if messages and isinstance(messages[0], dict):
        messages[0]["content"] = _splice(messages[0].get("content") or "")
    instr = out.get("instructions")
    if isinstance(instr, dict) and instr.get("system_prompt"):
        instr["system_prompt"] = _splice(instr["system_prompt"])
    return out
