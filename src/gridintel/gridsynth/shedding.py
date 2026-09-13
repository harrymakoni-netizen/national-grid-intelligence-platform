"""Load-shedding: generation of a plausible group schedule and its
application to true consumption.

The schedule shape (groups rotating through morning/evening blocks) is a
documented, representative approximation of publicly-reported ZESA
load-shedding patterns, NOT a transcription of a specific real published
schedule -- no single authoritative schedule was sourced in this milestone.
It exists to expose every downstream model to *a* plausible shedding
distortion, which Section 12.1 requires; it is not a claim about ZESA's
actual current schedule and must not be reported as one.

Shedding is assigned per transformer (every connection beneath a
transformer shares the same group), which is deliberate: Section 11.1 lists
"connections fed by the same transformer share ... shedding windows" as one
of the signals used to infer the connection-to-transformer association, so
the generator's shedding model must reproduce exactly that structure for
Module A/B development to be meaningful against it.
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


def generate_shedding_schedule(
    n_groups: int, *, seed: int
) -> dict[int, list[SheddingWindow]]:
    """One representative morning block and one evening block per group per
    weekday, offset by group so groups don't all shed simultaneously.
    Weekends are lighter, matching commonly reported practice of easing
    shedding on weekends when industrial demand is lower.
    """
    rng = np.random.default_rng(seed)
    schedule: dict[int, list[SheddingWindow]] = {}
    for group in range(n_groups):
        offset = (24 / n_groups) * group
        windows = []
        for dow in range(5):  # weekdays
            morning_start = (5 + offset) % 24
            windows.append(SheddingWindow(dow, morning_start, (morning_start + 4) % 24))
            evening_start = (17 + offset) % 24
            windows.append(SheddingWindow(dow, evening_start, (evening_start + 4) % 24))
        for dow in range(5, 7):  # weekends: one shorter evening block
            evening_start = (18 + offset) % 24
            windows.append(SheddingWindow(dow, evening_start, (evening_start + 2) % 24))
        schedule[group] = windows
    return schedule


def assign_groups_to_transformers(
    transformer_ids: list[str], n_groups: int, *, seed: int
) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    groups = rng.integers(0, n_groups, size=len(transformer_ids))
    return {tid: int(g) for tid, g in zip(transformer_ids, groups)}


def _in_window(hour: float, window: SheddingWindow) -> bool:
    if window.start_hour <= window.end_hour:
        return window.start_hour <= hour < window.end_hour
    return hour >= window.start_hour or hour < window.end_hour  # wraps past midnight


def shed_mask_for_group(
    index: pd.DatetimeIndex, windows: list[SheddingWindow]
) -> np.ndarray:
    hours = index.hour + index.minute / 60
    dows = index.dayofweek.to_numpy()
    mask = np.zeros(len(index), dtype=bool)
    for w in windows:
        mask |= (dows == w.dow) & np.array([_in_window(h, w) for h in hours])
    return mask


def apply_shedding(
    consumption: pd.DataFrame,
    *,
    transformer_by_connection: dict[str, str],
    group_by_transformer: dict[str, int],
    schedule: dict[int, list[SheddingWindow]],
    restoration_bump: float = 1.3,
) -> pd.DataFrame:
    """Zero out (near-zero standby draw) consumption during a connection's
    assigned shedding windows, flag those intervals, and apply a modest
    demand bump on the interval immediately following restoration
    (reconnection inrush / catch-up demand) -- a first-order approximation
    of the physical effect Section 7.2 requires the twin to account for.
    """
    out = consumption.copy()
    out["shed"] = False

    STANDBY_FRACTION = 0.05  # residual draw during an outage (fridge thermal mass, etc.)

    for conn_id in out["connection_id"].unique():
        rows = out["connection_id"] == conn_id
        idx = pd.DatetimeIndex(out.loc[rows, "ts"])
        transformer_id = transformer_by_connection[conn_id]
        group = group_by_transformer[transformer_id]
        mask = shed_mask_for_group(idx, schedule[group])

        kw = out.loc[rows, "kw"].to_numpy().copy()
        kw[mask] = kw[mask] * STANDBY_FRACTION

        restored = (~mask) & np.roll(mask, 1)
        restored[0] = False
        kw[restored] = kw[restored] * restoration_bump

        out.loc[rows, "kw"] = kw
        out.loc[rows, "shed"] = mask

    return out
