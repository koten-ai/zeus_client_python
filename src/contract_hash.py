#!/usr/bin/env python3
"""
Local fallback contract hash computation + stamped hash extraction (Zeus_Python).

In the normal flow you no longer compute hashes on the client.
You load a standardized V2 chat_request, send it to Zeus via the Catalog
"Verify with Zeus" button (/api/server_contract_hash → real /verify), and
save the stamped response that comes back. That file carries the correct
hash from the server (`contract.hash` or `_hash`).

Use `extract_stamped_hash()` (from this module or via `from app import ...`)
to read it from a loaded stamped file.

This module is only for:
- completely offline scenarios
- legacy unstamped files
- internal diagnostics when you suspect the loaded file is not the stamped one

It must stay roughly in sync with the server's strip logic for those rare cases.
"""

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SCOPE_BRIEF_MARKER = "\n\n## SCOPE BRIEF"
MINI_SCHEMA_MARKER = "\n\n## MINI-SCHEMA"

# Mirrors server / v4 _hash_policy and _strip_for_hash below. Used by the
# catalog conflict linter (ZC-35) and docs so "locked vs open" stays in one place.
HASH_EXCLUDED_ROOTS: tuple[str, ...] = (
    "guidance",   # advisory: optimal_paths, injections.business_logic, debug, …
    "contract",   # stamp metadata only
    "metadata",   # advisory
    "_*",         # underscore-prefixed operator/tooling keys
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


def _strip_scope_brief(content: str) -> str:
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
        out = {}
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            if k in ("targets", "model", "tool_choice", "temperature", "top_p", "max_tokens"):
                continue
            if k == "guidance":
                # Advisory only (optimal_paths, future facet suggestions, etc.).
                # Must never affect the contract hash. Matches Go stripForHash.
                continue
            if k == "contract":
                # The "contract" block is purely metadata (id, hash, computed_at,
                # built_at, builder, etc.) added at stamp/verify time. It must be excluded
                # from the hash computation so that identical rules content
                # (the developer's declared verbs, instructions, masq, scripting, etc.)
                # always produces the identical hash, regardless of when or
                # in which environment (dev/qa/prod, same scope) the file was stamped.
                # The hash is the "fingerprint of what the developer created and said
                # they are using." Timestamps etc. are just carriers in the stamped artifact.
                # This is the "same chat_request*.json → same hash" invariant.
                continue
            if k == "metadata":
                # Per v4 _hash_policy (prototype + IDEA/MASTER): "metadata" is
                # advisory/minimal and excluded from the hash (just like guidance/contract).
                # Prevents any generated_at or other varying data from leaking in.
                continue
            out[k] = _strip_for_hash(v)
        return out
    elif isinstance(obj, list):
        return [_strip_for_hash(x) for x in obj]
    elif isinstance(obj, str):
        # Brief (SCOPE BRIEF / MINI-SCHEMA) is runtime-injected advisory content.
        # Must never affect the contract hash, no matter where it lands in the
        # payload (legacy messages or V2 instructions.system_prompt etc.).
        # Strip from any string so publish/verify hashes match runtime validation
        # for the same rules content (same-builder invariant).
        return _strip_scope_brief(obj)
    else:
        return obj


def _canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        if obj.get("role") == "system" and isinstance(obj.get("content"), str):
            cp = dict(obj)
            cp["content"] = _strip_scope_brief(obj["content"])
            return {k: _canonicalize(v) for k, v in sorted(cp.items())}
        return {k: _canonicalize(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [_canonicalize(x) for x in obj]
    else:
        return obj


def compute_contract_hash(chat_request: dict) -> str:
    """Compute the contract hash (local fallback only).

    DEPRECATED for the happy path when using standardized 5TH stamped files
    (the recommended artifacts produced by Zeus Workbench "Verify & Download Stamped",
    /api/server_contract_hash with embed, or publish responses).

    Preferred: after loading a stamped file, call extract_stamped_hash(doc)
    (or from app: from app import extract_stamped_hash)
    (or read doc["contract"]["hash"] / doc["_hash"]). The server
    (/admin/api/contracts/verify and /contract) is the *sole* source of the
    authoritative hash. This local implementation is kept only for:
      - completely unstamped or legacy catalogs
      - offline / no-Zeus scenarios
      - diagnostics ("what would this compute to right now?")

    Must stay in sync with internal/contract/hash.go (both /verify+/contract
    publish paths and runtime ValidatePayload in session create use the
    same Hash after the same strip/canonicalize). The string stripping for
    brief markers was extended to cover V2 shapes (instructions.system_prompt
    etc.) so that runtime brief injection never affects the hash.
    """
    if not isinstance(chat_request, dict):
        return ""
    cleaned = _strip_for_hash(chat_request)
    canon = _canonicalize(cleaned)
    # ensure_ascii=False + Go-style HTML escapes on & < > so the compact JSON *bytes*
    # exactly match what Go encoding/json.Marshal emits (it runs HTMLEscape on string
    # content, turning & -> \u0026 , < -> \u003c , > -> \u003e , plus raw UTF-8 for other
    # non-ascii). This makes the local fallback produce the identical digest as the
    # server contract.Hash for the same rules content. Essential for diagnostics,
    # "embedded == current" checks, and no false drift warnings after stamping.
    text = json.dumps(canon, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    text = text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    blob = text.encode("utf-8")
    digest = hashlib.md5(blob).hexdigest()
    return "md5:" + digest


def resolve_session_contract_hash(
    bound_hash: str,
    stamped_hash: str,
    payload_hash: str,
) -> tuple[str, str]:
    """Pick ``contract_hash`` for ``/v2/session`` APIs.

    Zeus compares ``contract_hash`` to the hash of the ``chat_request`` body.
    Config bindings and embedded stamps are advisory; when they drift from the
    payload we must send the payload hash or session create returns 409 drift.
    """
    if payload_hash:
        if stamped_hash and stamped_hash == payload_hash:
            return payload_hash, "stamped_matches_payload"
        if bound_hash and bound_hash == payload_hash:
            return payload_hash, "config_matches_payload"
        return payload_hash, "payload_hash"
    if stamped_hash:
        return stamped_hash, "stamped_fallback"
    return bound_hash or "", "config_fallback"


def extract_stamped_hash(doc: dict) -> str:
    """Happy-path extractor for the authoritative server hash from a stamped
    standardized 5TH chat_request (the output of /verify or a publish that
    returned stamped_chat_request, or a pre-stamped snapshot file).

    Returns the value from (in priority order):
      - doc["contract"]["hash"]  (preferred, full 5TH envelope)
      - doc["_hash"] or top-level "hash" (various stamp response shapes)
      - also looks inside a possible "stamped_chat_request" wrapper

    When present, middle-man code should use this directly for the
    contract_hash sent on /v2/session (and traces). No local recompute,
    no drift risk from strip differences. Only fall back to
    compute_contract_hash for completely unstamped/legacy files or offline mode.

    Placeholders like "md5:TO_BE_FILLED..." are explicitly treated as "no real hash".
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
    # Direct on the loaded doc (the common case for pre-stamped snapshots or
    # after the user saved a "Copy stamped standardized JSON").
    for i, candidate in enumerate((doc, doc.get("stamped_chat_request") or {}, doc.get("stamped") or {})):
        if not isinstance(candidate, dict):
            continue
        cb = candidate.get("contract") or {}
        if isinstance(cb, dict):
            h = (cb.get("hash") or "").strip()
            if _is_real(h):
                logger.debug(f"extract_stamped_hash: found in candidate[{i}].contract.hash (len={len(h)})")
                return h
        for k in ("_hash", "hash"):
            h = (candidate.get(k) or "").strip()
            if _is_real(h):
                logger.debug(f"extract_stamped_hash: found in candidate[{i}].{k} (len={len(h)})")
                return h
    logger.debug("extract_stamped_hash: no (real) stamped hash found in doc or wrappers")
    return ""
