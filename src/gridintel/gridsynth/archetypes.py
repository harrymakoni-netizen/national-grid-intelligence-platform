"""Per-connection true consumption generation, differentiated by customer
archetype.

Two archetypes (high-density low-income, medium-density residential) reuse
the REAL diurnal and weekly shape from load_shapes.load_reference_shape()
directly -- only the mean consumption level and noise volatility differ,
both literature-informed. The other two (small commercial, industrial) use
a shape that is NOT derived from a real dataset -- Appendix C names no
public commercial/industrial interval dataset acquired in this milestone --
and are built from a documented, explicit business-hours / near-flat
template instead. This is a real limitation, not a hidden one: see
ARCHETYPE_SHAPE_SOURCE below, which every validation report must be able to
cite per connection archetype.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gridintel.db.models import ConnectionArchetype
from gridintel.gridsynth.load_shapes import load_reference_shape, resample_profile
from gridintel.gridsynth.topology import ConnectionSpec

ARCHETYPE_SHAPE_SOURCE = {
    ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: "real (UCI household dataset, scaled)",
    ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: "real (UCI household dataset, scaled)",
    ConnectionArchetype.SMALL_COMMERCIAL: "assumed (business-hours template, not fitted to real commercial data)",
    ConnectionArchetype.INDUSTRIAL: "assumed (near-flat shift-pattern template, not fitted to real industrial data)",
}

# (lognormal mean_kw range as (low, high) for np.random.uniform on log scale,
# multiplicative noise std-dev per interval, weekend/weekday behaviour)
ARCHETYPE_PARAMS = {
    ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: dict(
        mean_kw_range=(0.10, 0.35), volatility=0.35
    ),
    ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: dict(
        mean_kw_range=(0.4, 1.6), volatility=0.25
    ),
    ConnectionArchetype.SMALL_COMMERCIAL: dict(
        mean_kw_range=(1.0, 4.0), volatility=0.20
    ),
    ConnectionArchetype.INDUSTRIAL: dict(
        mean_kw_range=(15.0, 80.0), volatility=0.08
    ),
}


def _business_hours_diurnal(n_slots: int) -> np.ndarray:
    """Documented template (not fitted to data): low overnight, ramps up
    08:00, plateau through the business day, tapers by 18:00."""
    hours = np.arange(n_slots) * (24 / n_slots)
    base = 0.25 + 0.75 * (
        1 / (1 + np.exp(-(hours - 7.5))) - 1 / (1 + np.exp(-(hours - 18.5)))
    )
    return base / base.mean()


def _near_flat_diurnal(n_slots: int) -> np.ndarray:
    """Documented template (not fitted to data): near-constant industrial
    load with a modest night-shift dip 00:00-04:00."""
    hours = np.arange(n_slots) * (24 / n_slots)
    dip = np.where((hours >= 0) & (hours < 4), 0.82, 1.0)
    return dip / dip.mean()


@dataclass
class ArchetypeShape:
    diurnal: np.ndarray  # length = slots per day at target interval
    weekly: np.ndarray  # length 7, Monday=0


def build_archetype_shape(archetype: ConnectionArchetype, interval_minutes: int) -> ArchetypeShape:
    n_slots = int(24 * 60 / interval_minutes)
    ref = load_reference_shape()

    if archetype in (
        ConnectionArchetype.HIGH_DENSITY_LOW_INCOME,
        ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL,
    ):
        diurnal = resample_profile(ref["diurnal_profile_by_half_hour"], 48, interval_minutes)
        weekly = np.array(ref["weekly_profile_by_dow"])
    elif archetype == ConnectionArchetype.SMALL_COMMERCIAL:
        diurnal = _business_hours_diurnal(n_slots)
        weekly = np.array([1.1, 1.1, 1.1, 1.1, 1.15, 0.5, 0.35])
    elif archetype == ConnectionArchetype.INDUSTRIAL:
        diurnal = _near_flat_diurnal(n_slots)
        weekly = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.85, 0.75])
    else:
        raise ValueError(f"unknown archetype {archetype}")

    diurnal = diurnal / diurnal.mean()
    weekly = weekly / weekly.mean()
    return ArchetypeShape(diurnal=diurnal, weekly=weekly)


def generate_true_consumption(
    connections: list[ConnectionSpec],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
    seed: int,
) -> pd.DataFrame:
    """True per-connection consumption (kW), before load-shedding is
    applied. Long-form DataFrame: connection_id, ts, kw.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, end, freq=f"{interval_minutes}min", inclusive="left")
    n_slots_per_day = int(24 * 60 / interval_minutes)
    slot_of_day = ((index.hour * 60 + index.minute) // interval_minutes).to_numpy()
    dow = index.dayofweek.to_numpy()

    shapes: dict[ConnectionArchetype, ArchetypeShape] = {
        a: build_archetype_shape(a, interval_minutes) for a in ARCHETYPE_PARAMS
    }

    frames = []
    for conn in connections:
        params = ARCHETYPE_PARAMS[conn.archetype]
        shape = shapes[conn.archetype]

        conn_rng = np.random.default_rng(rng.integers(0, 2**32 - 1))
        log_low, log_high = np.log(params["mean_kw_range"][0]), np.log(params["mean_kw_range"][1])
        mean_kw = float(np.exp(conn_rng.uniform(log_low, log_high)))

        base = mean_kw * shape.diurnal[slot_of_day] * shape.weekly[dow]
        noise = conn_rng.lognormal(mean=0.0, sigma=params["volatility"], size=len(index))
        # Multiplicative noise with unit mean so it doesn't bias the archetype's mean level.
        noise = noise / np.exp(params["volatility"] ** 2 / 2)
        kw = np.clip(base * noise, 0, None)

        frames.append(
            pd.DataFrame({"connection_id": conn.connection_id, "ts": index, "kw": kw})
        )

    return pd.concat(frames, ignore_index=True)
