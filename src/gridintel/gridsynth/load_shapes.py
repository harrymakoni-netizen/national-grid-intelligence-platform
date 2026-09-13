"""Loaders for the real public data that calibrates the generator:

- reference_load_shape.json: diurnal/weekly/monthly shape derived from the
  UCI household power consumption dataset (scripts/process_public_dataset.py).
- harare_irradiance_hourly.csv: real hourly surface irradiance for Harare
  from NASA POWER (satellite reanalysis, the Appendix C-named source that is
  also the intended production source for this data).

Both are committed as small, git-tracked, pre-processed artefacts so
generation and tests never require network access or the raw 130MB dataset.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"


@lru_cache(maxsize=1)
def load_reference_shape() -> dict:
    path = DATA_DIR / "reference_load_shape.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run scripts/process_public_dataset.py first."
        )
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def load_irradiance_series() -> pd.Series:
    path = DATA_DIR / "harare_irradiance_hourly.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df["ghi_w_m2"]


def resample_profile(profile: list[float], source_slots_per_day: int, interval_minutes: int) -> np.ndarray:
    """Linearly interpolate a periodic daily profile (e.g. 48 half-hourly
    slots) onto a different interval length, wrapping at the day boundary.
    """
    source = np.asarray(profile, dtype=float)
    minutes_per_slot = 24 * 60 / source_slots_per_day
    source_minutes = np.arange(source_slots_per_day) * minutes_per_slot

    n_target = int(24 * 60 / interval_minutes)
    target_minutes = np.arange(n_target) * interval_minutes

    # Wrap-around interpolation: extend source by one period on each side.
    ext_minutes = np.concatenate(
        [source_minutes - 24 * 60, source_minutes, source_minutes + 24 * 60]
    )
    ext_values = np.concatenate([source, source, source])
    return np.interp(target_minutes, ext_minutes, ext_values)


def irradiance_for_period(
    start: pd.Timestamp, end: pd.Timestamp, interval_minutes: int
) -> pd.Series:
    """Real Harare irradiance resampled/tiled onto the requested period at
    the requested interval. The cached record covers ~59 days; longer
    scenario windows tile it (with a deterministic day-of-year offset)
    rather than fabricating additional days, so every irradiance value used
    is a real measurement, just possibly reused across a longer synthetic
    window.
    """
    series = load_irradiance_series()
    freq = f"{interval_minutes}min"
    target_index = pd.date_range(start, end, freq=freq, inclusive="left")

    src = series.copy()
    src.index = src.index.tz_localize(None)
    src_upsampled = src.resample(freq).interpolate("linear")

    n_src = len(src_upsampled)
    out = np.empty(len(target_index))
    for i in range(len(target_index)):
        out[i] = src_upsampled.iloc[i % n_src]
    return pd.Series(out, index=target_index, name="ghi_w_m2")
