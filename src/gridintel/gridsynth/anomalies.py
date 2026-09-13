"""Injects labelled ground-truth anomalies into a subset of connections at
known times: partial bypass, full bypass, meter failure, vacancy, and solar
adoption.

The key modelling decision here is that every anomaly is expressed as a
transformation from a single `kw` (physical) series into a pair of series:

- `kw`: what actually flows from the transformer -- unaffected by meter
  bypass or failure, because diverting or disabling a meter does not change
  how much energy the household draws. This is what the digital twin's
  power-flow solution and transformer-level loading must reflect.
- `metered_kw`: what the meter would register, which drives the purchasing
  simulation. Equal to `kw` unless bypass or failure is active.

Bypass and meter failure are therefore given the SAME physical/metered
split and differ only in their ground-truth label -- deliberately, because
distinguishing them from consumption data alone is supposed to be hard
(Section 8.2 lists them as genuinely confusable), and making them
artificially separable in the generator would produce a Module B evaluation
that looks better than the real problem. Vacancy and solar both reduce the
PHYSICAL draw, which is the actual discriminating signal against bypass/
failure at the transformer level.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gridintel.db.models import AnomalyType
from gridintel.gridsynth.load_shapes import irradiance_for_period
from gridintel.gridsynth.topology import ConnectionSpec

# PLACEHOLDER: representative, not measured. Confirm ranges against
# confirmed historical audit outcomes once any exist (Section 8.2 stage 2).
PARTIAL_BYPASS_FRACTION_RANGE = (0.3, 0.7)
FULL_BYPASS_RESIDUAL_METERED_FRACTION = 0.02
METER_FAILURE_RESIDUAL_METERED_FRACTION = 0.0
VACANCY_RESIDUAL_PHYSICAL_FRACTION = 0.02  # standby draw (shared fridge, security light, etc.)

# Rooftop PV sizing and response, expressed relative to a plausible
# household/commercial capacity range in kW and a simple linear
# irradiance-to-output response with a nameplate-efficiency-like coefficient.
SOLAR_CAPACITY_KW_RANGE = (1.0, 5.0)
SOLAR_REFERENCE_IRRADIANCE_W_M2 = 1000.0  # STC reference


@dataclass
class AnomalyRecord:
    connection_id: str
    anomaly_type: AnomalyType
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp | None
    parameters: dict


def _pick_targets(
    connections: list[ConnectionSpec], fraction: float, rng: np.random.Generator, exclude: set[str]
) -> list[str]:
    candidates = [c.connection_id for c in connections if c.connection_id not in exclude]
    n = max(1, int(round(len(candidates) * fraction))) if candidates else 0
    if n == 0 or not candidates:
        return []
    return list(rng.choice(candidates, size=min(n, len(candidates)), replace=False))


def inject_anomalies(
    consumption: pd.DataFrame,
    connections: list[ConnectionSpec],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
    rates: dict[AnomalyType, float],
    seed: int,
) -> tuple[pd.DataFrame, list[AnomalyRecord]]:
    """consumption must have columns connection_id, ts, kw (physical, post-
    shedding). Returns a new DataFrame with an added `metered_kw` column
    (equal to `kw` outside any anomaly window) and the list of injected
    ground-truth anomaly records.
    """
    rng = np.random.default_rng(seed)
    out = consumption.copy()
    out["metered_kw"] = out["kw"]

    used: set[str] = set()
    records: list[AnomalyRecord] = []

    # Anomalies start at a random point after the first 15% of the window,
    # so every case has real pre-anomaly baseline behaviour to contrast against.
    window_start_floor = start + (end - start) * 0.15

    def random_start() -> pd.Timestamp:
        span_intervals = int((end - window_start_floor) / pd.Timedelta(minutes=interval_minutes) * 0.7)
        offset_intervals = int(rng.integers(0, max(span_intervals, 1)))
        return window_start_floor.ceil(f"{interval_minutes}min") + pd.Timedelta(
            minutes=interval_minutes * offset_intervals
        )

    irradiance = None  # computed lazily, only if solar targets exist

    for anomaly_type, rate in rates.items():
        targets = _pick_targets(connections, rate, rng, used)
        used.update(targets)

        for connection_id in targets:
            mask_rows = out["connection_id"] == connection_id
            idx = out.index[mask_rows]
            ts = out.loc[idx, "ts"]
            anomaly_start = random_start()
            active = ts >= anomaly_start

            if anomaly_type == AnomalyType.PARTIAL_BYPASS:
                frac = float(rng.uniform(*PARTIAL_BYPASS_FRACTION_RANGE))
                out.loc[idx[active], "metered_kw"] = out.loc[idx[active], "kw"] * (1 - frac)
                params = {"bypass_fraction": frac}

            elif anomaly_type == AnomalyType.FULL_BYPASS:
                out.loc[idx[active], "metered_kw"] = (
                    out.loc[idx[active], "kw"] * FULL_BYPASS_RESIDUAL_METERED_FRACTION
                )
                params = {"residual_metered_fraction": FULL_BYPASS_RESIDUAL_METERED_FRACTION}

            elif anomaly_type == AnomalyType.METER_FAILURE:
                out.loc[idx[active], "metered_kw"] = (
                    out.loc[idx[active], "kw"] * METER_FAILURE_RESIDUAL_METERED_FRACTION
                )
                params = {}

            elif anomaly_type == AnomalyType.VACANCY:
                out.loc[idx[active], "kw"] = out.loc[idx[active], "kw"] * VACANCY_RESIDUAL_PHYSICAL_FRACTION
                out.loc[idx[active], "metered_kw"] = out.loc[idx[active], "kw"]
                params = {"residual_physical_fraction": VACANCY_RESIDUAL_PHYSICAL_FRACTION}

            elif anomaly_type == AnomalyType.SOLAR_ADOPTION:
                if irradiance is None:
                    irradiance = irradiance_for_period(start, end, interval_minutes)
                capacity_kw = float(rng.uniform(*SOLAR_CAPACITY_KW_RANGE))
                ghi = irradiance.reindex(pd.DatetimeIndex(ts)).to_numpy()
                pv_output_kw = capacity_kw * np.clip(ghi, 0, None) / SOLAR_REFERENCE_IRRADIANCE_W_M2
                pv_output_kw = np.nan_to_num(pv_output_kw)

                reduced = np.clip(out.loc[idx, "kw"].to_numpy() - pv_output_kw, 0, None)
                new_kw = out.loc[idx, "kw"].to_numpy().copy()
                new_kw[active.to_numpy()] = reduced[active.to_numpy()]
                out.loc[idx, "kw"] = new_kw
                out.loc[idx, "metered_kw"] = out.loc[idx, "kw"]
                params = {"capacity_kw": capacity_kw}

            else:
                raise ValueError(f"unhandled anomaly type {anomaly_type}")

            records.append(
                AnomalyRecord(
                    connection_id=connection_id,
                    anomaly_type=anomaly_type,
                    start_ts=anomaly_start,
                    end_ts=None,
                    parameters=params,
                )
            )

    return out, records
