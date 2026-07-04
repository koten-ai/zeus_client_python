"""TOON encoding for LLM tool results."""
import json

try:
    from toon import encode as _toon_encode
except Exception:
    _toon_encode = None


def to_toon(text):
    """Re-encode a JSON tool-result string as TOON. Falls back to the
    original text if TOON is unavailable or the body isn't JSON. Pure
    CPU + tiny, so it stays synchronous (no benefit from awaiting)."""
    if not _toon_encode:
        return text
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text  # not JSON (e.g. an error string) — leave as-is
    try:
        return _toon_encode(obj)
    except Exception:
        return text
