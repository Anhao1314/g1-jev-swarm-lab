"""Joint-limit guard for initial-state perturbations.

Phase 1.2 may expand joint perturbations, but a sampled state must never leave
the model's legal joint range. The guard clips offsets to the reported limits
and reports how many entries were clipped, so the evidence records that the
sampled state was adjusted rather than pretended to be legal.
"""

from __future__ import annotations

import numpy as np


def clip_joint_offsets(
    positions: np.ndarray, offsets: np.ndarray, low: np.ndarray, high: np.ndarray
) -> tuple[np.ndarray, int]:
    """Return offsets that keep ``positions + offsets`` inside ``[low, high]``."""

    positions = np.asarray(positions, dtype=np.float64)
    offsets = np.asarray(offsets, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    if not (positions.shape == offsets.shape == low.shape == high.shape):
        raise ValueError("positions, offsets, low and high must share the same shape")
    if not np.all(np.isfinite(offsets)):
        raise ValueError("offsets contain non-finite values")
    if np.any(low > high):
        raise ValueError("low limit exceeds high limit")
    proposed = positions + offsets
    clipped = np.clip(proposed, low, high)
    clipped_count = int(np.count_nonzero(np.abs(clipped - proposed) > 1e-12))
    return clipped - positions, clipped_count
