"""
Convert the raw UCI "Individual household electric power consumption"
dataset (Appendix C: public smart-meter trial data) into two compact,
git-tracked artefacts used by the generator and its test suite:

1. data/processed/reference_load_shape.json
   Normalised diurnal profile (mean by half-hour-of-day), weekly pattern
   (mean by day-of-week) and load factor, computed from real interval data.
   This is the calibration target gridsynth.load_shapes fits archetype
   shapes against, and what gridsynth.validate compares generated scenarios
   to (Section 15's acceptance criterion for the generator).

2. data/processed/held_out_interval_sample.csv
   A held-out slice of real half-hourly consumption (kW), kept aside as
   ground truth for evaluating Module A's reconstruction later (Section
   8.1 / 12.2) -- never used to fit anything, only to score against.

Source: https://archive.ics.uci.edu/dataset/235 (single household, Sceaux,
France, Dec 2006 - Nov 2010, minute resolution). This is ONE real
household, not a population -- it supplies a genuine diurnal/weekly shape
template, not archetype-level population variance. Archetype
differentiation (income/density/commercial/industrial) is built on top of
this real shape via documented, literature-informed scaling -- see
gridsynth/archetypes.py, which states this explicitly rather than implying
the archetype split itself is drawn from real data it is not.

Run once: `python scripts/process_public_dataset.py`. Requires
data/public/household_power_consumption.txt (fetched separately; see
README in data/public/ -- the raw file is gitignored, these outputs are not).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW_PATH = Path(__file__).resolve().parents[1] / "data" / "public" / "household_power_consumption.txt"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def load_raw() -> pd.DataFrame:
    df = pd.read_csv(
        RAW_PATH,
        sep=";",
        na_values=["?"],
        usecols=["Date", "Time", "Global_active_power"],
        low_memory=False,
    )
    df = df.dropna(subset=["Global_active_power"])
    df["timestamp"] = pd.to_datetime(
        df["Date"] + " " + df["Time"], format="%d/%m/%Y %H:%M:%S"
    )
    df = df.set_index("timestamp").sort_index()
    return df


def to_half_hourly_kw(df: pd.DataFrame) -> pd.Series:
    # Global_active_power is in kW already, minute-sampled; mean-resample.
    s = df["Global_active_power"].resample("30min").mean()
    return s.dropna()


WINDOW_WEEKS_FOR_LOAD_FACTOR = [1, 2, 4, 8, 12, 26, 52]


def _windowed_load_factors(series: pd.Series, weeks: int) -> float:
    """Mean load factor (mean/max) over non-overlapping windows of the
    given length. A load factor computed over a short window is not
    comparable to one computed over the full multi-year record -- a longer
    window is mechanically more likely to contain a rare extreme peak or
    trough, which lowers mean/max regardless of anything about the
    underlying shape. Generated scenarios are typically a few weeks long,
    so the reference must be windowed the same way to be a fair target.
    """
    window = pd.Timedelta(weeks=weeks)
    start = series.index.min()
    end = series.index.max()
    factors = []
    cursor = start
    while cursor + window <= end:
        chunk = series[cursor : cursor + window]
        if len(chunk) > 0 and chunk.max() > 0:
            factors.append(chunk.mean() / chunk.max())
        cursor += window
    return float(np.mean(factors)) if factors else float("nan")


def build_reference(series: pd.Series) -> dict:
    df = series.to_frame("kw")
    df["half_hour"] = df.index.hour * 2 + (df.index.minute // 30)
    df["dow"] = df.index.dayofweek
    df["month"] = df.index.month

    overall_mean = df["kw"].mean()

    diurnal = df.groupby("half_hour")["kw"].mean() / overall_mean
    weekly = df.groupby("dow")["kw"].mean() / overall_mean
    monthly = df.groupby("month")["kw"].mean() / overall_mean

    load_factor = df["kw"].mean() / df["kw"].max()
    windowed_load_factor = {
        weeks: _windowed_load_factors(series, weeks) for weeks in WINDOW_WEEKS_FOR_LOAD_FACTOR
    }

    return {
        "source": "UCI Individual household electric power consumption "
        "(archive.ics.uci.edu/dataset/235), single household, Sceaux FR, "
        "resampled to 30-minute mean active power",
        "n_intervals": int(len(df)),
        "overall_mean_kw": float(overall_mean),
        "load_factor": float(load_factor),
        "load_factor_by_window_weeks": {
            str(k): v for k, v in windowed_load_factor.items()
        },
        "diurnal_profile_by_half_hour": [
            float(diurnal.get(h, np.nan)) for h in range(48)
        ],
        "weekly_profile_by_dow": [float(weekly.get(d, np.nan)) for d in range(7)],
        "monthly_profile": [float(monthly.get(m, np.nan)) for m in range(1, 13)],
    }


def main() -> None:
    if not RAW_PATH.exists():
        raise SystemExit(
            f"raw dataset not found at {RAW_PATH}. Download it first: "
            "curl -L -o data/public/household_power_consumption.zip "
            "https://archive.ics.uci.edu/static/public/235/individual+household+electric+power+consumption.zip "
            "&& unzip it into data/public/"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw = load_raw()
    half_hourly = to_half_hourly_kw(raw)

    # Last 90 days held out untouched: used only to score reconstruction
    # later, never to fit the reference shape below.
    cutoff = half_hourly.index.max() - pd.Timedelta(days=90)
    fit_series = half_hourly[half_hourly.index <= cutoff]
    held_out = half_hourly[half_hourly.index > cutoff]

    reference = build_reference(fit_series)
    (OUT_DIR / "reference_load_shape.json").write_text(json.dumps(reference, indent=2))

    held_out.rename("kw").to_frame().to_csv(OUT_DIR / "held_out_interval_sample.csv")

    print(f"fit period: {fit_series.index.min()} .. {fit_series.index.max()} ({len(fit_series)} intervals)")
    print(f"held-out period: {held_out.index.min()} .. {held_out.index.max()} ({len(held_out)} intervals)")
    print(f"load factor (fit period): {reference['load_factor']:.3f}")
    print(f"wrote {OUT_DIR / 'reference_load_shape.json'}")
    print(f"wrote {OUT_DIR / 'held_out_interval_sample.csv'}")


if __name__ == "__main__":
    main()
