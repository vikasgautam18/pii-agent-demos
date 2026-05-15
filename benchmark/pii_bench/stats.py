"""Just the few percentiles we report. No statistical tests, no IQR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class Summary:
    label: str
    n: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


def summarise(samples: Sequence[float], label: str) -> Summary:
    if not samples:
        raise ValueError(f"empty samples for {label!r}")
    a = np.asarray(samples, dtype=float)
    p50, p95, p99 = np.percentile(a, [50, 95, 99])
    return Summary(
        label=label,
        n=int(a.size),
        mean_ms=float(a.mean()),
        p50_ms=float(p50),
        p95_ms=float(p95),
        p99_ms=float(p99),
    )
