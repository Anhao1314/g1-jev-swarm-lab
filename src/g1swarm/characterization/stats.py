"""Small numpy-based statistics helpers (no extra dependencies)."""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np


def summarize(values: Iterable[float]) -> dict[str, float | int | None]:
    """n / mean / median / std / min / max for a sequence of floats."""

    array = np.asarray([float(value) for value in values], dtype=np.float64)
    if array.size == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
        }
    std = float(np.std(array, ddof=1)) if array.size > 1 else 0.0
    return {
        "n": int(array.size),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "std": std,
        "min": float(np.min(array)),
        "max": float(np.max(array)),
    }


def bootstrap_ci(
    values: Sequence[float],
    *,
    samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> list[float] | None:
    """Simple percentile bootstrap confidence interval for the mean."""

    array = np.asarray([float(value) for value in values], dtype=np.float64)
    if array.size < 2:
        return None
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(array, size=(int(samples), array.size), replace=True)
    means = draws.mean(axis=1)
    alpha = (1.0 - float(confidence)) / 2.0
    return [float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))]


def is_deterministic(values: Iterable[object], *, atol: float = 1e-12) -> bool:
    """True when all values agree within ``atol`` (numbers) or are equal (objects)."""

    items = list(values)
    if len(items) < 2:
        return True
    first = items[0]
    if isinstance(first, (int, float, np.floating)):
        array = np.asarray([float(value) for value in items], dtype=np.float64)
        return bool(np.max(np.abs(array - array[0])) <= atol)
    return all(item == first for item in items)
