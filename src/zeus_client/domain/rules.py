"""Named rules{} merge / freeze (CHECKLIST C · ZC-WISH-002/003).

SDK defaults ∪ tenant ∪ request. Append-only mid-session. Never a contract stamp.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from zeus_client.config.models import ClientSettings
from zeus_client.domain.policy import JAILBREAK_RULE_IDS, default_jailbreak_rules

__all__ = [
    "merge_rules",
    "merge_rules_frozen",
    "ruleset_id_for",
    "freeze_session_rules",
    "append_session_rules",
]


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
        filtered: dict[str, str] = {}
        for key, text in req.items():
            if key in JAILBREAK_RULE_IDS and not override_defaults:
                if not str(text).strip():
                    raise ValueError(
                        f"cannot clear default jailbreak rule {key!r} unless override_defaults=True"
                    )
                # I1: request overlay cannot reword SDK/tenant jailbreak keys.
                continue
            filtered[key] = text
        pack.update({k: v for k, v in filtered.items() if str(v).strip() or override_defaults})
    return pack


def merge_rules_frozen(
    base: Mapping[str, str],
    overlay: Mapping[str, str],
    *,
    frozen: bool = False,
) -> dict[str, str]:
    """Named merge used by conformance L2: freeze blocks overlay of existing keys."""
    out = {str(k): str(v) for k, v in base.items()}
    for k, v in overlay.items():
        sk = str(k)
        if frozen and sk in out:
            continue
        out[sk] = str(v)
    return out


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
