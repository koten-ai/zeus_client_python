"""Token-bucket rate limiter (SECURITY §11 — typeahead default 10 rps / burst 20)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

__all__ = ["TokenBucket", "TokenBucketLimiter"]


@dataclass
class TokenBucket:
    """Thread-safe token bucket. ``rate`` tokens/sec, capacity ``burst``."""

    rate: float = 10.0
    burst: float = 20.0
    _tokens: float = field(init=False)
    _updated: float = field(init=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be > 0")
        if self.burst <= 0:
            raise ValueError("burst must be > 0")
        self._tokens = float(self.burst)
        self._updated = time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        """Return True and consume ``cost`` tokens when available."""
        if cost <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            elapsed = max(0.0, now - self._updated)
            self._updated = now
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    def reset(self) -> None:
        with self._lock:
            self._tokens = float(self.burst)
            self._updated = time.monotonic()


@dataclass
class TokenBucketLimiter:
    """Named surface → bucket map (e.g. ``typeahead``)."""

    buckets: dict[str, TokenBucket] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def configure(self, surface: str, *, rate: float, burst: float) -> TokenBucket:
        b = TokenBucket(rate=rate, burst=burst)
        with self._lock:
            self.buckets[surface] = b
        return b

    def allow(self, surface: str, cost: float = 1.0) -> bool:
        with self._lock:
            bucket = self.buckets.get(surface)
        if bucket is None:
            return True  # no limit configured → allow
        return bucket.allow(cost)
