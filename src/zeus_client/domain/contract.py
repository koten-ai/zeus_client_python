"""Contract hash domain — local compute, stamp extract, session resolve, heal.

Port of V1 ``zeus_client.contract_hash`` algorithms for the V2 hexagonal core.
Hub remains the sole authority for production stamps; this module is for:

- offline / unstamped catalogs
- diagnostics (\"what would this compute to?\")
- session bind when payload vs stamp/bound drift (prefer payload)

Never invent production stamps. Domain only — no httpx / network.
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "SCOPE_BRIEF_MARKER",
    "MINI_SCHEMA_MARKER",
    "HASH_EXCLUDED_ROOTS",
    "HASH_EXCLUDED_STRING_MARKERS",
    "LOCKED_POINTERS",
    "SessionHashChoice",
    "compute_contract_hash",
    "extract_stamped_hash",
    "resolve_session_contract_hash",
    "heal_trailing_ws_stamp_drift",
    "ContractService",
]

SCOPE_BRIEF_MARKER = "\n\n## SCOPE BRIEF"
MINI_SCHEMA_MARKER = "\n\n## MINI-SCHEMA"

# Mirrors server / v4 _hash_policy and _strip_for_hash below.
HASH_EXCLUDED_ROOTS: tuple[str, ...] = (
    "guidance",  # advisory: optimal_paths, injections.business_logic, debug, …
    "contract",  # stamp metadata only
    "metadata",  # advisory
    "_*",  # underscore-prefixed operator/tooling keys
)
# Runtime string suffixes after these markers are also stripped for hash.
HASH_EXCLUDED_STRING_MARKERS: tuple[str, ...] = (
    SCOPE_BRIEF_MARKER.strip(),
    MINI_SCHEMA_MARKER.strip(),
)
# JSON-pointer style paths that participate in the contract hash (locked rules).
LOCKED_POINTERS: tuple[str, ...] = (
    "/instructions/system_prompt",
    "/instructions/verb_usage_guide",
    "/instructions/verb_order",
    "/instructions/response_expectations",
    "/masq",
    "/verbs",
    "/messages/*/content",
)

_TRAILING_WS = " \t\n\r"


@dataclass(frozen=True, slots=True)
class SessionHashChoice:
    """Result of picking ``contract_hash`` for ``/v2/session`` APIs."""

    hash: str
    source: str


def _strip_scope_brief(content: Any) -> str:
    if not isinstance(content, str):
        return ""
    for marker in (SCOPE_BRIEF_MARKER, MINI_SCHEMA_MARKER):
        i = content.find(marker)
        if i >= 0:
            prefix = content[:i]
            # Match Go stripScopeBrief exactly: TrimRight(..., " \t\n\r")
            return prefix.rstrip(" \t\n\r")
    return content


def _strip_for_hash(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            if k in ("targets", "model", "tool_choice", "temperature", "top_p", "max_tokens"):
                continue
            if k == "guidance":
                # Advisory only — must never affect the contract hash.
                continue
            if k == "contract":
                # Stamp metadata only (id, hash, computed_at, builder, …).
                continue
            if k == "metadata":
                # Advisory/minimal — excluded like guidance/contract.
                continue
            out[k] = _strip_for_hash(v)
        return out
    if isinstance(obj, list):
        return [_strip_for_hash(x) for x in obj]
    if isinstance(obj, str):
        # Brief markers are runtime-injected advisory content.
        return _strip_scope_brief(obj)
    return obj


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        if obj.get("role") == "system" and isinstance(obj.get("content"), str):
            cp = dict(obj)
            cp["content"] = _strip_scope_brief(obj["content"])
            return {k: _canonicalize(v) for k, v in sorted(cp.items())}
        return {k: _canonicalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_canonicalize(x) for x in obj]
    return obj


def compute_contract_hash(chat_request: dict) -> str:
    """Compute the contract hash (local fallback only).

    Preferred happy path: load a Hub-stamped file and use
    :func:`extract_stamped_hash`. Local compute is for unstamped/legacy/
    offline/diagnostics and must stay in sync with Zeus ``contract.Hash``
    strip + canonicalize + Go ``encoding/json`` HTML escapes.
    """
    if not isinstance(chat_request, dict):
        return ""
    cleaned = _strip_for_hash(chat_request)
    canon = _canonicalize(cleaned)
    # ensure_ascii=False + Go-style HTML escapes on & < > so compact JSON
    # bytes match encoding/json.Marshal (\\u0026 / \\u003c / \\u003e).
    text = json.dumps(canon, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    text = text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    blob = text.encode("utf-8")
    digest = hashlib.md5(blob).hexdigest()
    return "md5:" + digest


def resolve_session_contract_hash(
    bound_hash: str,
    stamped_hash: str,
    payload_hash: str,
) -> SessionHashChoice:
    """Pick ``contract_hash`` for ``/v2/session`` APIs.

    Zeus compares ``contract_hash`` to the hash of the ``chat_request`` body.
    Config bindings and embedded stamps are advisory; when they drift from the
    payload we must send the payload hash or session create returns 409 drift.
    """
    if payload_hash:
        if stamped_hash and stamped_hash == payload_hash:
            return SessionHashChoice(payload_hash, "stamped_matches_payload")
        if bound_hash and bound_hash == payload_hash:
            return SessionHashChoice(payload_hash, "config_matches_payload")
        return SessionHashChoice(payload_hash, "payload_hash")
    if stamped_hash:
        return SessionHashChoice(stamped_hash, "stamped_fallback")
    return SessionHashChoice(bound_hash or "", "config_fallback")


def extract_stamped_hash(doc: dict) -> str:
    """Extract the authoritative server hash from a stamped chat_request.

    Priority: ``contract.hash`` → ``_hash`` / ``hash`` on doc, then the same
    keys under ``stamped_chat_request`` / ``stamped`` wrappers.

    Placeholders like ``md5:TO_BE_FILLED...`` are treated as absent.
    """
    if not isinstance(doc, dict):
        logger.debug("extract_stamped_hash: doc not dict")
        return ""

    def _is_real(h: str) -> bool:
        if not h:
            return False
        hs = h.strip()
        if "TO_BE_FILLED" in hs:
            return False
        return True

    for i, candidate in enumerate(
        (doc, doc.get("stamped_chat_request") or {}, doc.get("stamped") or {})
    ):
        if not isinstance(candidate, dict):
            continue
        cb = candidate.get("contract") or {}
        if isinstance(cb, dict):
            h = (cb.get("hash") or "").strip()
            if _is_real(h):
                logger.debug(
                    "extract_stamped_hash: found in candidate[%s].contract.hash (len=%s)",
                    i,
                    len(h),
                )
                return h
        for k in ("_hash", "hash"):
            h = (candidate.get(k) or "").strip()
            if _is_real(h):
                logger.debug(
                    "extract_stamped_hash: found in candidate[%s].%s (len=%s)",
                    i,
                    k,
                    len(h),
                )
                return h
    logger.debug("extract_stamped_hash: no (real) stamped hash found in doc or wrappers")
    return ""


def _rstrip_system_prompt_surfaces(doc: dict) -> tuple[dict, bool]:
    """Shallow-normalized copy with trailing ws stripped from system text.

    Only touches surfaces that participate in the contract hash as rules text:
    ``messages[0].content`` and ``instructions.system_prompt``. Leaves content
    alone when a SCOPE BRIEF / MINI-SCHEMA marker is already present.
    """
    if not isinstance(doc, dict):
        return doc, False
    out = deepcopy(doc)
    changed = False

    messages = out.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        content = messages[0].get("content")
        if isinstance(content, str) and content:
            if (
                SCOPE_BRIEF_MARKER.strip() not in content
                and MINI_SCHEMA_MARKER.strip() not in content
            ):
                stripped = content.rstrip(_TRAILING_WS)
                if stripped != content:
                    messages[0]["content"] = stripped
                    changed = True

    instr = out.get("instructions")
    if isinstance(instr, dict):
        sp = instr.get("system_prompt")
        if isinstance(sp, str) and sp:
            if SCOPE_BRIEF_MARKER.strip() not in sp and MINI_SCHEMA_MARKER.strip() not in sp:
                stripped = sp.rstrip(_TRAILING_WS)
                if stripped != sp:
                    instr["system_prompt"] = stripped
                    out["instructions"] = instr
                    changed = True

    return out, changed


def _rewrite_embedded_hash(doc: dict, old_hash: str, new_hash: str) -> None:
    """Update known stamp locations in-place when healing trailing-ws drift."""
    if not isinstance(doc, dict) or not old_hash or not new_hash or old_hash == new_hash:
        return
    cb = doc.get("contract")
    if isinstance(cb, dict) and (cb.get("hash") or "").strip() == old_hash:
        cb["hash"] = new_hash
    if (doc.get("_hash") or "").strip() == old_hash:
        doc["_hash"] = new_hash
    if (doc.get("hash") or "").strip() == old_hash:
        doc["hash"] = new_hash


def heal_trailing_ws_stamp_drift(doc: dict) -> dict:
    """Heal stamp vs runtime hash drift caused only by trailing system-prompt whitespace.

    When the embedded stamp equals ``compute(raw)`` and rstripping system-prompt
    surfaces alone changes the digest, rewrite the embedded stamp to the
    normalized hash and rstrip those surfaces. Does not rewrite stamps that
    already disagree for other reasons (never forges production stamps).
    """
    if not isinstance(doc, dict):
        return doc
    stamped = extract_stamped_hash(doc)
    if not stamped:
        return doc
    try:
        h_raw = compute_contract_hash(doc)
    except Exception:
        return doc
    if stamped != h_raw:
        return doc

    normalized, changed = _rstrip_system_prompt_surfaces(doc)
    if not changed:
        return doc
    try:
        h_norm = compute_contract_hash(normalized)
    except Exception:
        return doc
    if not h_norm or h_norm == h_raw:
        return doc

    _rewrite_embedded_hash(normalized, stamped, h_norm)
    logger.info(
        "heal_trailing_ws_stamp_drift: rewrote stamp %s -> %s "
        "(trailing system-prompt whitespace; aligns stamp with post-brief-merge hash)",
        stamped,
        h_norm,
    )
    return normalized


class ContractService:
    """Thin façade matching IG Phase 4 ``ContractService`` surface."""

    def compute_hash(self, chat_request: dict) -> str:
        return compute_contract_hash(chat_request)

    def extract_stamped_hash(self, doc: dict) -> str:
        return extract_stamped_hash(doc)

    def resolve_session_hash(
        self,
        *,
        stamped: str,
        content: str,
        bound: str,
    ) -> SessionHashChoice:
        # IG names: stamped / content / bound → V1 order bound, stamped, payload
        return resolve_session_contract_hash(bound, stamped, content)

    def heal_trailing_ws_drift(self, doc: dict) -> dict:
        return heal_trailing_ws_stamp_drift(doc)
