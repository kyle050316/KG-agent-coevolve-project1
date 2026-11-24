"""Statistics used for reporting, following Miller (2024), "Adding Error Bars to Evals":
Wilson intervals for proportions, cluster bootstrap (clusters = anchor entities) for means and
paired differences, exact McNemar for paired binary outcomes, Holm correction, Cohen's kappa.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Sequence

import numpy as np
from scipy.stats import binomtest


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def _clusters(values: Sequence[float], clusters: Sequence[str]) -> list[np.ndarray]:
    groups: dict[str, list[float]] = defaultdict(list)
    for v, c in zip(values, clusters):
        groups[c].append(float(v))
    return [np.asarray(g) for g in groups.values()]


def cluster_bootstrap(values: Sequence[float], clusters: Sequence[str], n_boot: int = 10000,
                      seed: int = 0, alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean with a percentile CI from resampling whole clusters."""
    vals = np.asarray(values, dtype=float)
    if len(vals) == 0:
        return float("nan"), float("nan"), float("nan")
    groups = _clusters(values, clusters)
    sums = np.array([g.sum() for g in groups])
    ns = np.array([len(g) for g in groups])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    boots = sums[idx].sum(1) / ns[idx].sum(1)
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return float(vals.mean()), float(lo), float(hi)


def paired_cluster_bootstrap(a: Sequence[float], b: Sequence[float], clusters: Sequence[str], n_boot: int = 10000,
                             seed: int = 0) -> dict:
    """Mean of (a - b) over paired items, cluster-bootstrap CI and two-sided bootstrap p-value."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    mean, lo, hi = cluster_bootstrap(d, clusters, n_boot, seed)
    groups = _clusters(d, clusters)
    sums = np.array([g.sum() for g in groups])
    ns = np.array([len(g) for g in groups])
    rng = np.random.default_rng(seed + 1)
    idx = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    boots = sums[idx].sum(1) / ns[idx].sum(1)
    p = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return {"diff": mean, "lo": lo, "hi": hi, "p_boot": float(min(1.0, p)), "n": int(len(d))}


def mcnemar_exact(a: Sequence[int], b: Sequence[int]) -> dict:
    """Exact McNemar test on paired binary outcomes."""
    b01 = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    b10 = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    n = b01 + b10
    p = 1.0 if n == 0 else binomtest(b10, n, 0.5).pvalue
    return {"b01": b01, "b10": b10, "p": float(p)}


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda x: x[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def cohen_kappa(y1: Sequence, y2: Sequence) -> float:
    labels = sorted(set(y1) | set(y2), key=str)
    n = len(y1)
    if n == 0:
        return float("nan")
    po = sum(1 for a, b in zip(y1, y2) if a == b) / n
    pe = sum((list(y1).count(l) / n) * (list(y2).count(l) / n) for l in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def fmt_ci(p: float, lo: float, hi: float, pct: bool = True) -> str:
    if any(math.isnan(x) for x in (p, lo, hi)):
        return "n/a"
    f = 100 if pct else 1
    return f"{p * f:.1f} [{lo * f:.1f}, {hi * f:.1f}]"
