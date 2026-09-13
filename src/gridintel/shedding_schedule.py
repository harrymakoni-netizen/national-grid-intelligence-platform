"""The shedding schedule data structure and mask computation, shared by
the synthetic generator (which invents a plausible schedule) and Module A
(which conditions its consumption prior on a schedule -- synthetic today,
ZESA's actually-published one later, per Section 9.1). Deliberately has no
dependency on gridsynth, matching the same reasoning as network_catalog.py:
a real deployment's schedule is not synthetically generated, so anything
that consumes a schedule must not depend on the package that invents one.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SheddingWindow:
    dow: int  # 0=Monday
    start_hour: float
    end_hour: float


def _in_window(hour: float, window: SheddingWindow) -> bool:
    if window.start_hour <= window.end_hour:
        return window.start_hour <= hour < window.end_hour
    return hour >= window.start_hour or hour < window.end_hour  # wraps past midnight


def shed_mask_for_group(index: pd.DatetimeIndex, windows: list[SheddingWindow]) -> np.ndarray:
    hours = index.hour + index.minute / 60
    dows = index.dayofweek.to_numpy()
    mask = np.zeros(len(index), dtype=bool)
    for w in windows:
        mask |= (dows == w.dow) & np.array([_in_window(h, w) for h in hours])
    return mask
