"""Redaction at journal / log boundaries — secrets never enter event bodies.

Policy aligned with docs/V2/SECURITY.md §8.2 and family API_LOGGING REDACT rules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = [
    "REDACTED",
    "Redactor",
    "DefaultRedactor",
    "default_redactor",
    "SENSITIVE_HEADER_NAMES",
    "SENSITIVE_KEY_RE",
]

REDACTED = "[REDACTED]"

# Header names compared case-insensitively.
SENSITIVE_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
        "x-auth-token",
        "x-access-token",
    }
)

# JSON object keys (and similar) matching this pattern get value redaction.
SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|api[_-]?key|token|authorization|auth|credential|"
    r"credit[_-]?card|ssn|private[_-]?key)",
    re.IGNORECASE,
)

# Bearer / Basic / raw key-ish tokens in free text.
_BEARER_RE = re.compile(r"(?i)\b(authorization\s*:\s*)?(bearer|basic)\s+\S+")
_SK_RE = re.compile(r"(?i)\b(sk-[a-z0-9\-_]{8,}|xai-[a-z0-9\-_]{8,})\b")


class Redactor:
    """Protocol-shaped base; use DefaultRedactor / default_redactor()."""

    def headers(self, h: Mapping[str, str]) -> dict[str, str]:
        raise NotImplementedError

    def json_value(self, v: Any, *, path: str = "$") -> Any:
        raise NotImplementedError

    def text(self, s: str, *, max_chars: int) -> str:
        raise NotImplementedError


class DefaultRedactor(Redactor):
    """Default production redactor (hard-deny secrets)."""

    def headers(self, h: Mapping[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in h.items():
            if str(k).lower() in SENSITIVE_HEADER_NAMES:
                out[str(k)] = REDACTED
            else:
                out[str(k)] = str(v)
        return out

    def json_value(self, v: Any, *, path: str = "$") -> Any:
        return self._walk(v, path=path)

    def text(self, s: str, *, max_chars: int) -> str:
        if s is None:
            return ""
        text = str(s)
        text = _BEARER_RE.sub(REDACTED, text)
        text = _SK_RE.sub(REDACTED, text)
        if max_chars >= 0 and len(text) > max_chars:
            if max_chars == 0:
                return "…"
            return text[:max_chars] + "…"
        return text

    def _walk(self, v: Any, *, path: str) -> Any:
        if isinstance(v, Mapping):
            out: dict[str, Any] = {}
            for k, child in v.items():
                key = str(k)
                child_path = f"{path}.{key}"
                if SENSITIVE_KEY_RE.search(key):
                    out[key] = REDACTED
                else:
                    out[key] = self._walk(child, path=child_path)
            return out
        if isinstance(v, list):
            return [self._walk(item, path=f"{path}[{i}]") for i, item in enumerate(v)]
        if isinstance(v, tuple):
            return [self._walk(item, path=f"{path}[{i}]") for i, item in enumerate(v)]
        if isinstance(v, str):
            # Only scrub obvious credential patterns in string leaves.
            if _BEARER_RE.search(v) or _SK_RE.search(v):
                return REDACTED
            return v
        # bool/int/float/None and other JSON-safe scalars
        return v


def default_redactor() -> DefaultRedactor:
    """Factory for the default redactor instance."""
    return DefaultRedactor()
