"""Client settings bag + named rules merge/freeze (base-5 control plane).

ZC-WISH-002/003/007 — PROMPT_SETTINGS merge algorithm.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

from zeus_client.agent.jailbreak_defaults import (
    JAILBREAK_RULE_IDS,
    default_jailbreak_rules,
)

# company_context word budgets (ZC-WISH-006)
COMPANY_CONTEXT_SOFT_WORDS = 150
COMPANY_CONTEXT_HARD_WORDS = 250


@dataclass
class ClientSettings:
    """First-class structured settings for a turn/session (not free-form essays)."""

    locale: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    channel: Optional[str] = None
    market: Optional[str] = None
    deployment_id: Optional[str] = None
    ruleset_id: Optional[str] = None
    company_context: Optional[str] = None
    # {app: {fields: {name: {type, description}}}}
    output_request: Optional[dict] = None
    # named rules {id: text}; merged with SDK defaults + tenant
    rules: Optional[dict[str, str]] = None
    # tenant pack applied before request.rules
    tenant_rules: Optional[dict[str, str]] = None
    override_defaults: bool = False
    max_rounds: Optional[int] = None
    # message_* boilerplate for policy chrome
    messages: dict[str, str] = field(default_factory=dict)
    # sticky OR flags from prior turns
    sticky_flags: dict[str, bool] = field(default_factory=dict)
    # dual-read boolean[] triggers for one release (ZC-WISH-005)
    allow_array_triggers: bool = True
    # app_output bad types: "strip" | "fail"
    app_output_on_error: str = "strip"
    # force return when remaining rounds <= this (ZC-WISH-021); None = off
    force_return_rounds_left: Optional[int] = 1
    redaction: Optional[dict] = None
    # soft-require policy_action when brand/company inject present
    soft_require_policy_action: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ClientSettings":
        if raw is None:
            return cls()
        if isinstance(raw, ClientSettings):
            return raw
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in dict(raw).items() if k in known}
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)


def _as_rules_object(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        out: dict[str, str] = {}
        for k, v in raw.items():
            if v is None:
                continue
            out[str(k)] = v if isinstance(v, str) else json.dumps(v, sort_keys=True)
        return out
    if isinstance(raw, list):
        # legacy list of strings or {id, rule} dicts — one-release bridge
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


def merge_rules(
    *,
    tenant_rules: Mapping[str, str] | None = None,
    request_rules: Mapping[str, str] | None = None,
    override_defaults: bool = False,
    include_sdk_defaults: bool = True,
) -> dict[str, str]:
    """SDK defaults ∪ tenant ∪ request (later wins). Protect default jailbreak keys."""
    pack = default_jailbreak_rules() if include_sdk_defaults else {}
    if tenant_rules:
        pack.update(_as_rules_object(tenant_rules))
    req = _as_rules_object(request_rules)
    if req:
        if not override_defaults:
            for key in JAILBREAK_RULE_IDS:
                if key in pack and key not in req:
                    # deletion of default key via omit is OK (union); explicit null not in dict
                    pass
            # Explicit empty-string delete attempt
            for key, text in list(req.items()):
                if key in JAILBREAK_RULE_IDS and not str(text).strip():
                    raise ValueError(
                        f"cannot clear default jailbreak rule {key!r} "
                        f"unless override_defaults=True"
                    )
        pack.update({k: v for k, v in req.items() if str(v).strip() or override_defaults})
    return pack


def ruleset_id_for(pack: Mapping[str, str]) -> str:
    """Stable short id for a frozen rules pack (not a contract stamp)."""
    canonical = json.dumps(dict(sorted(pack.items())), ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"rules:{digest}"


def freeze_session_rules(settings: ClientSettings) -> tuple[dict[str, str], str]:
    """Merge and freeze rules; return (rules_frozen, ruleset_id)."""
    pack = merge_rules(
        tenant_rules=settings.tenant_rules,
        request_rules=settings.rules,
        override_defaults=settings.override_defaults,
    )
    rid = settings.ruleset_id or ruleset_id_for(pack)
    return pack, rid


def append_session_rules(
    frozen: Mapping[str, str],
    additions: Mapping[str, str],
) -> dict[str, str]:
    """Append-only mid-session rule adds (cannot rewrite existing ids)."""
    out = dict(frozen)
    for k, v in _as_rules_object(additions).items():
        if k in out and out[k] != v:
            raise ValueError(
                f"mid-session rule id {k!r} already frozen; use a new id or new session"
            )
        out[k] = v
    return out


def validate_output_request(output_request: Any) -> dict:
    """Reject type-only app fields (need type + description). ZC-WISH-008."""
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
        warnings.append(
            f"company_context truncated hard {n} → {hard_words} words"
        )
        return " ".join(words[:hard_words]), warnings
    if n > soft_words:
        warnings.append(
            f"company_context over soft budget ({n} > {soft_words} words)"
        )
    return text, warnings


def prepare_settings(settings: ClientSettings | Mapping | None) -> ClientSettings:
    """Normalize settings: validate output_request, freeze ruleset_id."""
    s = ClientSettings.from_mapping(settings if not isinstance(settings, ClientSettings) else settings.to_dict())
    if isinstance(settings, ClientSettings):
        s = deepcopy(settings)
    if s.output_request is not None:
        s.output_request = validate_output_request(s.output_request)
    pack, rid = freeze_session_rules(s)
    s.rules = pack
    s.ruleset_id = rid
    if s.company_context:
        s.company_context, _ = truncate_company_context(s.company_context)
    return s
