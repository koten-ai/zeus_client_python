"""Content-addressed payload store — SHA-256 refs, dedup identical bytes."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["PayloadRecord", "InMemoryPayloadStore", "PayloadStore"]


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    ref: str
    content_type: str
    kind: str
    sha256: str
    size: int
    data: bytes


class PayloadStore:
    """Protocol-shaped store API."""

    def put(self, data: bytes, *, content_type: str, kind: str) -> str:
        raise NotImplementedError

    def get(self, ref: str) -> bytes | None:
        raise NotImplementedError

    def meta(self, ref: str) -> PayloadRecord | None:
        raise NotImplementedError


@dataclass
class InMemoryPayloadStore(PayloadStore):
    """Process-local content-addressed blob store."""

    _by_ref: dict[str, PayloadRecord] = field(default_factory=dict)

    def put(self, data: bytes, *, content_type: str, kind: str) -> str:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("payload data must be bytes")
        raw = bytes(data)
        digest = hashlib.sha256(raw).hexdigest()
        ref = f"sha256:{digest}"
        existing = self._by_ref.get(ref)
        if existing is not None:
            return ref
        self._by_ref[ref] = PayloadRecord(
            ref=ref,
            content_type=content_type,
            kind=kind,
            sha256=digest,
            size=len(raw),
            data=raw,
        )
        return ref

    def get(self, ref: str) -> bytes | None:
        rec = self._by_ref.get(ref)
        return None if rec is None else rec.data

    def meta(self, ref: str) -> PayloadRecord | None:
        return self._by_ref.get(ref)

    def items(self) -> Mapping[str, PayloadRecord]:
        return dict(self._by_ref)
