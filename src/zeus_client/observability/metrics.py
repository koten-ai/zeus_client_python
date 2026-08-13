"""Process-local metrics counters (BEST_PRACTICES §5.2 names).

No Prometheus dependency required — apps can scrape ``snapshot()`` or plug a
custom ``MetricsPort``. Labels stay low-cardinality.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol, runtime_checkable

__all__ = [
    "MetricsPort",
    "InMemoryMetrics",
    "NullMetrics",
    "get_default_metrics",
    "set_default_metrics",
]


def _label_key(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


@runtime_checkable
class MetricsPort(Protocol):
    def incr(
        self, name: str, *, labels: Mapping[str, str] | None = None, amount: float = 1.0
    ) -> None: ...

    def observe(
        self, name: str, value: float, *, labels: Mapping[str, str] | None = None
    ) -> None: ...

    def snapshot(self) -> dict[str, object]: ...


@dataclass
class InMemoryMetrics:
    """Thread-safe in-process counters + simple sum/count histograms."""

    _lock: Lock = field(default_factory=Lock, repr=False)
    _counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float)),
        repr=False,
    )
    _hist_sum: dict[str, dict[tuple[tuple[str, str], ...], float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float)),
        repr=False,
    )
    _hist_count: dict[str, dict[tuple[tuple[str, str], ...], int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int)),
        repr=False,
    )

    def incr(
        self, name: str, *, labels: Mapping[str, str] | None = None, amount: float = 1.0
    ) -> None:
        key = _label_key(labels)
        with self._lock:
            self._counters[name][key] += float(amount)

    def observe(self, name: str, value: float, *, labels: Mapping[str, str] | None = None) -> None:
        key = _label_key(labels)
        with self._lock:
            self._hist_sum[name][key] += float(value)
            self._hist_count[name][key] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters: dict[str, list[dict[str, object]]] = {}
            for name, series in self._counters.items():
                counters[name] = [
                    {"labels": dict(lbl), "value": val} for lbl, val in series.items()
                ]
            histograms: dict[str, list[dict[str, object]]] = {}
            for name, series in self._hist_sum.items():
                rows: list[dict[str, object]] = []
                for lbl, s in series.items():
                    c = self._hist_count[name][lbl]
                    rows.append(
                        {
                            "labels": dict(lbl),
                            "sum": s,
                            "count": c,
                            "avg": (s / c) if c else 0.0,
                        }
                    )
                histograms[name] = rows
            return {"counters": counters, "histograms": histograms}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._hist_sum.clear()
            self._hist_count.clear()


class NullMetrics:
    """No-op metrics sink."""

    def incr(
        self, name: str, *, labels: Mapping[str, str] | None = None, amount: float = 1.0
    ) -> None:
        return None

    def observe(self, name: str, value: float, *, labels: Mapping[str, str] | None = None) -> None:
        return None

    def snapshot(self) -> dict[str, object]:
        return {"counters": {}, "histograms": {}}


_default: MetricsPort = InMemoryMetrics()


def get_default_metrics() -> MetricsPort:
    return _default


def set_default_metrics(metrics: MetricsPort) -> None:
    global _default
    _default = metrics
