"""Hash-excluded control-plane inject (base-5 / ZC-WISH control plane).

Splices company_context, named rules{}, output_request, and settings meta
AFTER ``## SCOPE BRIEF`` / ``## MINI-SCHEMA`` markers so ``compute_contract_hash``
stays stable (same strip boundary as scope brief / business_logic inject).

No brief marker → no splice (avoids thrashing the stamp).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Mapping

__all__ = [
    "COMPANY_CONTEXT_SOFT_WORDS",
    "COMPANY_CONTEXT_HARD_WORDS",
    "COMPANY_HEADING",
    "RULES_HEADING",
    "OUTPUT_REQUEST_HEADING",
    "SETTINGS_META_HEADING",
    "InjectSettings",
    "truncate_company_context",
    "validate_output_request",
    "prepare_inject_settings",
    "render_company_context",
    "render_rules_block",
    "render_output_request_block",
    "render_settings_meta",
    "build_inject_block",
    "apply_control_plane_inject",
]

COMPANY_CONTEXT_SOFT_WORDS = 150
COMPANY_CONTEXT_HARD_WORDS = 250

COMPANY_HEADING = "## Company context"
RULES_HEADING = "## Rules"
OUTPUT_REQUEST_HEADING = "## Output request"
SETTINGS_META_HEADING = "## Session settings"


@dataclass(frozen=True, slots=True)
class InjectSettings:
    """Control-plane inject bag (subset of V1 ClientSettings used for splice)."""

    locale: str | None = None
    language: str | None = None
    timezone: str | None = None
    channel: str | None = None
    market: str | None = None
    deployment_id: str | None = None
    ruleset_id: str | None = None
    company_context: str | None = None
    # {app: {fields: {name: {type, description}}}}
    output_request: Mapping[str, Any] | None = None
    # named rules {id: text}
    rules: Mapping[str, str] | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> InjectSettings:
        if raw is None:
            return cls()
        if isinstance(raw, InjectSettings):
            return raw
        known = {
            "locale",
            "language",
            "timezone",
            "channel",
            "market",
            "deployment_id",
            "ruleset_id",
            "company_context",
            "output_request",
            "rules",
        }
        kwargs = {k: v for k, v in dict(raw).items() if k in known}
        # Normalize rules to str→str
        if "rules" in kwargs and kwargs["rules"] is not None:
            kwargs["rules"] = _as_rules_object(kwargs["rules"])
        return cls(**kwargs)


def _as_rules_object(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        out: dict[str, str] = {}
        for k, v in raw.items():
            if v is None:
                continue
            out[str(k)] = v if isinstance(v, str) else str(v)
        return out
    if isinstance(raw, list):
        out = {}
        for i, item in enumerate(raw):
            if isinstance(item, str):
                out[f"r{i + 1}"] = item
            elif isinstance(item, dict):
                rid = str(item.get("id") or f"r{i + 1}")
                text = item.get("rule") or item.get("text") or ""
                out[rid] = str(text)
        return out
    raise TypeError(f"rules must be dict or list, got {type(raw).__name__}")


def truncate_company_context(
    text: str | None,
    *,
    soft_words: int = COMPANY_CONTEXT_SOFT_WORDS,
    hard_words: int = COMPANY_CONTEXT_HARD_WORDS,
) -> tuple[str, list[str]]:
    """Soft/hard word budget for company_context. Returns (text, warnings)."""
    warnings: list[str] = []
    if not text:
        return "", warnings
    words = text.split()
    n = len(words)
    if n > hard_words:
        warnings.append(f"company_context truncated hard {n} → {hard_words} words")
        return " ".join(words[:hard_words]), warnings
    if n > soft_words:
        warnings.append(f"company_context over soft budget ({n} > {soft_words} words)")
    return text, warnings


def validate_output_request(output_request: Any) -> dict[str, Any]:
    """Reject type-only app fields (need type + description)."""
    if output_request is None:
        return {}
    if not isinstance(output_request, dict):
        raise TypeError("output_request must be a dict")
    app = output_request.get("app")
    if app is None:
        return deepcopy(output_request)
    if not isinstance(app, dict):
        raise TypeError("output_request.app must be a dict")
    fields = app.get("fields")
    if fields is None:
        return deepcopy(output_request)
    if not isinstance(fields, dict):
        raise TypeError("output_request.app.fields must be a dict")
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            raise ValueError(
                f"output_request.app.fields[{name!r}] must be "
                f"{{type, description}} object"
            )
        if "type" not in spec:
            raise ValueError(f"output_request field {name!r} missing type")
        desc = spec.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(
                f"output_request field {name!r} requires non-empty description "
                f"(type-only is not enough)"
            )
    return deepcopy(output_request)


def prepare_inject_settings(
    settings: InjectSettings | Mapping[str, Any] | None,
) -> InjectSettings:
    """Normalize inject settings: validate output_request, truncate company_context."""
    if isinstance(settings, InjectSettings):
        s = settings
    else:
        s = InjectSettings.from_mapping(settings)
    out_req = None
    if s.output_request is not None:
        out_req = validate_output_request(s.output_request)
    company = s.company_context
    if company:
        company, _ = truncate_company_context(company)
    rules = dict(s.rules) if s.rules else None
    return replace(
        s,
        output_request=out_req,
        company_context=company,
        rules=rules,
    )


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


def render_output_request_block(output_request: Mapping[str, Any] | None) -> str:
    if not output_request:
        return ""
    app = output_request.get("app") if isinstance(output_request, Mapping) else None
    fields = app.get("fields") if isinstance(app, Mapping) else None
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
        desc = (spec.get("description") or "").strip()
        tname = spec.get("type") or "string"
        lines.append(f"- {name} ({tname}): {desc}")
    return "\n".join(lines)


def render_settings_meta(settings: InjectSettings) -> str:
    bits: list[str] = []
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


def build_inject_block(settings: InjectSettings) -> tuple[str, list[str]]:
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


def apply_control_plane_inject(
    chat_req: dict,
    settings: InjectSettings,
) -> dict:
    """Deepcopy chat_req and splice inject block into system prompt(s).

    Idempotent on heading. No-op without brief markers. Returns original
    object when the inject block is empty.
    """
    block, _warnings = build_inject_block(settings)
    if not block.strip():
        return chat_req
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
