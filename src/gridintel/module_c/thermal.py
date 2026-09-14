"""Module C, stage 1: transformer thermal ageing and remaining useful life
(Section 8.3), computed from physics rather than from failure history.

Section 8.3 is explicit that this is how the module cold-starts: "Physics-
based thermal ageing models -- the loading guides for oil-immersed
transformers provide a standard relationship between hot-spot temperature
and insulation life -- supply a defensible prior, which is used to
constrain the learned model until sufficient observed failures
accumulate." No transformer in this system has failed, and no sensing
hardware exists, so the survival model those failures would train is not
built. This is the prior, and it is a real calculation, not a placeholder.

What it uses, all of which genuinely exists here:
  - per-transformer loading, from the digital twin's power-flow solution
  - nameplate rating and the load/no-load loss split, from network_catalog
  - real hourly ambient temperature for Harare (NASA POWER, the same
    reanalysis source Appendix C names and the intended production source)

Method (IEC 60076-7, loading guide for oil-immersed power transformers):

  top-oil rise      dTo = dTo_rated * ((1 + R*K^2) / (1 + R))^x
  hot-spot gradient dTh = dTh_rated * K^y
  hot-spot temp     Th  = ambient + dTo + dTh
  relative ageing   V   = 2^((Th - 98) / 6)
  loss of life      L   = integral of V dt

R is the ratio of load losses to no-load losses at rated load, taken from
each transformer's own catalog entry rather than assumed. V is the ageing
rate relative to operation at the 98 C reference hot-spot: V = 1 means
insulation is consumed at exactly its design rate, V = 2 means twice as
fast. Normal insulation life at the reference is 180,000 hours.

Oil thermal inertia is modelled as a first-order lag (tau ~ 3 h) rather
than assuming the oil reaches steady state within each 30-minute interval,
which would overstate the thermal response to short load peaks.

Limits worth stating plainly:
  - The rise-at-rated constants below are IEC defaults for ONAN
    distribution transformers, NOT nameplate values from a real fleet.
    Confirm against ZETDC asset records before any figure here informs a
    replacement decision.
  - Loading comes from reconstructed consumption, so it inherits Module
    A's error. A transformer whose load is underestimated will have its
    ageing underestimated too.
  - This is a thermal-ageing prior only. It says nothing about moisture
    ingress, partial discharge, bushing failure or vandalism, which are
    real failure modes this cannot see.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"

# IEC 60076-7 defaults for ONAN (oil natural, air natural) distribution
# transformers. PLACEHOLDER in the same sense as network_catalog.py:
# standard published values, not measurements from a real fleet.
TOP_OIL_RISE_RATED_K = 55.0   # top-oil rise over ambient at rated load
HOT_SPOT_GRADIENT_RATED_K = 23.0  # hot-spot to top-oil gradient at rated load
OIL_EXPONENT_X = 0.8
WINDING_EXPONENT_Y = 1.6
OIL_TIME_CONSTANT_H = 3.0

REFERENCE_HOT_SPOT_C = 98.0
AGEING_DOUBLING_K = 6.0        # ageing rate doubles per 6 K above reference
NORMAL_INSULATION_LIFE_H = 180_000.0  # ~20.55 years at the reference hot-spot

# IEC 60076-7 hot-spot limits for distribution transformers. These are
# published loading limits, not chosen thresholds, which is what makes a
# peak excursion against them worth reporting to an engineer.
HOT_SPOT_LIMIT_NORMAL_CYCLIC_C = 120.0
HOT_SPOT_LIMIT_LONG_TIME_EMERGENCY_C = 140.0

# Sustained ageing only becomes the binding constraint on a transformer's
# life when it approaches the design rate. Below this, insulation thermal
# ageing is not what will retire the unit -- moisture ingress, mechanical
# failure, lightning and vandalism dominate -- and quoting a thermal
# "remaining life" would be arithmetically true and practically absurd
# (this model happily produces 18,000 years for a lightly loaded unit).
THERMALLY_LIMITED_AGEING_RATE = 0.5


@lru_cache(maxsize=1)
def load_ambient_temperature() -> pd.Series:
    path = DATA_DIR / "harare_temperature_hourly.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Ambient temperature is fetched by "
            "scripts/fetch_weather.py (NASA POWER)."
        )
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df["temp_c"]


def ambient_for_period(index: pd.DatetimeIndex) -> np.ndarray:
    """Real Harare ambient temperature aligned to `index`. The cached
    record covers ~59 days; longer windows tile it rather than inventing
    additional days, so every value used is a real measurement.
    """
    series = load_ambient_temperature().copy()
    series.index = series.index.tz_localize(None)
    target = index.tz_localize(None) if index.tz is not None else index

    freq_minutes = int(round((target[1] - target[0]).total_seconds() / 60)) if len(target) > 1 else 60
    upsampled = series.resample(f"{freq_minutes}min").interpolate("linear")
    values = upsampled.to_numpy()
    if len(values) == 0:
        raise ValueError("no ambient temperature available")
    return np.array([values[i % len(values)] for i in range(len(target))])


@dataclass
class ThermalResult:
    ts: pd.DatetimeIndex
    load_factor: np.ndarray
    ambient_c: np.ndarray
    top_oil_c: np.ndarray
    hot_spot_c: np.ndarray
    ageing_rate: np.ndarray          # V, relative to design rate at 98 C
    interval_hours: float

    @property
    def equivalent_ageing_hours(self) -> float:
        """Insulation-life hours consumed over the observed window."""
        return float(np.sum(self.ageing_rate) * self.interval_hours)

    @property
    def observed_hours(self) -> float:
        return float(len(self.ts) * self.interval_hours)

    @property
    def mean_ageing_rate(self) -> float:
        return float(np.mean(self.ageing_rate))

    @property
    def peak_hot_spot_c(self) -> float:
        return float(np.max(self.hot_spot_c))

    @property
    def hours_above_reference(self) -> float:
        return float(np.sum(self.hot_spot_c > REFERENCE_HOT_SPOT_C) * self.interval_hours)

    @property
    def hours_above_cyclic_limit(self) -> float:
        """Hours spent above IEC 60076-7's normal-cyclic-loading hot-spot
        limit. A published limit being exceeded is a reportable fact; a
        threshold someone invented is not."""
        return float(
            np.sum(self.hot_spot_c > HOT_SPOT_LIMIT_NORMAL_CYCLIC_C) * self.interval_hours
        )

    @property
    def thermally_limited(self) -> bool:
        return self.mean_ageing_rate >= THERMALLY_LIMITED_AGEING_RATE

    @property
    def projected_life_years(self) -> float | None:
        """Insulation life if this loading pattern continued -- reported
        ONLY when thermal ageing is actually the binding constraint.
        Returns None otherwise, because at light loading this figure runs
        to hundreds or thousands of years and says nothing true about when
        the transformer will actually need replacing.
        """
        if not self.thermally_limited:
            return None
        return NORMAL_INSULATION_LIFE_H / max(self.mean_ageing_rate, 1e-6) / 8760.0

    @property
    def risk_band(self) -> str:
        """Banded on published IEC limits and sustained ageing rate, in
        that order -- a peak excursion above a loading limit matters even
        when the average is benign, which is exactly the case a
        mean-only metric misses."""
        if self.peak_hot_spot_c > HOT_SPOT_LIMIT_LONG_TIME_EMERGENCY_C or self.mean_ageing_rate > 4.0:
            return "critical"
        if self.peak_hot_spot_c > HOT_SPOT_LIMIT_NORMAL_CYCLIC_C or self.mean_ageing_rate > 2.0:
            return "high"
        if self.peak_hot_spot_c > 110.0 or self.mean_ageing_rate > 1.0:
            return "elevated"
        return "normal"


def compute_thermal_ageing(
    ts: pd.DatetimeIndex,
    load_kw: np.ndarray,
    *,
    rating_kva: float,
    no_load_loss_kw: float,
    load_loss_kw: float,
    power_factor: float = 0.95,
) -> ThermalResult:
    """Hot-spot temperature and insulation ageing for one transformer over
    the supplied loading series.
    """
    if len(ts) < 2:
        raise ValueError("need at least two intervals to compute ageing")

    interval_hours = (ts[1] - ts[0]).total_seconds() / 3600.0
    ambient = ambient_for_period(ts)

    # Load factor K, on apparent power against nameplate kVA.
    load_kva = np.asarray(load_kw, dtype=float) / max(power_factor, 1e-6)
    k = np.clip(load_kva / max(rating_kva, 1e-6), 0.0, None)

    # Loss ratio R from this transformer's own catalog entry.
    r = load_loss_kw / max(no_load_loss_kw, 1e-6)

    steady_top_oil_rise = TOP_OIL_RISE_RATED_K * ((1.0 + r * k**2) / (1.0 + r)) ** OIL_EXPONENT_X

    # First-order oil lag: the tank does not reach steady state within one
    # interval, so a short peak must not be treated as a sustained one.
    alpha = 1.0 - np.exp(-interval_hours / OIL_TIME_CONSTANT_H)
    top_oil_rise = np.empty_like(steady_top_oil_rise)
    previous = steady_top_oil_rise[0]
    for i, target in enumerate(steady_top_oil_rise):
        previous = previous + alpha * (target - previous)
        top_oil_rise[i] = previous

    hot_spot_gradient = HOT_SPOT_GRADIENT_RATED_K * k**WINDING_EXPONENT_Y

    top_oil_c = ambient + top_oil_rise
    hot_spot_c = top_oil_c + hot_spot_gradient
    ageing_rate = 2.0 ** ((hot_spot_c - REFERENCE_HOT_SPOT_C) / AGEING_DOUBLING_K)

    return ThermalResult(
        ts=ts,
        load_factor=k,
        ambient_c=ambient,
        top_oil_c=top_oil_c,
        hot_spot_c=hot_spot_c,
        ageing_rate=ageing_rate,
        interval_hours=interval_hours,
    )
