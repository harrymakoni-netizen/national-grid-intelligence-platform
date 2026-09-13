"""Section 15's acceptance criterion for the generator, made executable:

  "Generated load shapes are statistically indistinguishable from public
  reference data on diurnal profile, weekly pattern and load factor.
  Injected anomalies are recoverable by manual inspection of the ground
  truth."

Two independent checks:

1. compare_to_reference_shape(): generated residential consumption vs. the
   real UCI-derived reference shape (data/processed/reference_load_shape.json),
   on diurnal profile correlation, weekly profile correlation, and load
   factor. Only the two archetypes actually built from that reference
   (high-density low-income, medium-density residential) are compared --
   comparing the commercial/industrial templates against a household
   reference would not be a like-for-like test (see archetypes.py's
   ARCHETYPE_SHAPE_SOURCE for which archetypes that applies to).

2. check_anomaly_recoverability(): for every injected anomaly, confirms
   from the raw ground truth rows -- not a trained model -- that the
   expected signature is actually present (e.g. a bypass shows metered
   consumption falling while physical consumption does not). This is
   exactly "recoverable by manual inspection", automated so it runs every
   time a scenario is generated rather than only when someone remembers to
   look.

Every number this module returns must be reported as what it is: a
comparison between two labelled-synthetic-or-public quantities, never
presented as a measured result.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import (
    AnomalyType,
    Connection,
    ConnectionArchetype,
    GroundTruthAnomaly,
    GroundTruthConsumption,
)
from gridintel.gridsynth.load_shapes import load_reference_shape

RESIDENTIAL_ARCHETYPES = {
    ConnectionArchetype.HIGH_DENSITY_LOW_INCOME,
    ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL,
}


@dataclass
class ShapeComparison:
    diurnal_correlation: float
    weekly_correlation: float
    generated_load_factor: float
    reference_load_factor: float
    load_factor_relative_error: float
    n_connections: int
    n_intervals: int
    passes: bool
    tolerance_notes: str


def _nearest_windowed_load_factor(reference: dict, n_weeks: float) -> float:
    """The reference's load factor was computed window-matched at several
    durations (process_public_dataset.py) because load factor is not
    duration-invariant -- a longer window mechanically has a lower mean/max
    from rare extremes. Pick the precomputed window nearest the scenario's
    actual duration rather than falling back to the multi-year figure.
    """
    by_weeks = reference.get("load_factor_by_window_weeks")
    if not by_weeks:
        return float(reference["load_factor"])
    available = {int(k): v for k, v in by_weeks.items()}
    nearest = min(available, key=lambda w: abs(w - n_weeks))
    return float(available[nearest])


def compare_to_reference_shape(
    session: Session,
    scenario_id: str,
    *,
    min_correlation: float = 0.85,
    max_load_factor_relative_error: float = 0.5,
) -> ShapeComparison:
    reference = load_reference_shape()

    residential_ids = [
        cid
        for (cid,) in session.execute(
            select(Connection.id).where(
                Connection.archetype.in_([a.value for a in RESIDENTIAL_ARCHETYPES])
            )
        ).all()
    ]
    rows = session.execute(
        select(
            GroundTruthConsumption.connection_id,
            GroundTruthConsumption.ts,
            GroundTruthConsumption.kw,
            GroundTruthConsumption.shed,
        )
        .where(GroundTruthConsumption.scenario_id == scenario_id)
        .where(GroundTruthConsumption.connection_id.in_(residential_ids))
    ).all()
    df = pd.DataFrame(rows, columns=["connection_id", "ts", "kw", "shed"])
    df["ts"] = pd.to_datetime(df["ts"])
    # Load-shedding is a deliberate, documented distortion (Section 12.1) --
    # comparing shed intervals against an un-shed reference household would
    # understate the fit of the underlying archetype shape, not reveal a
    # flaw in it. Excluded here; shedding's own effect is validated
    # separately by shedding.py's own tests, not against this reference.
    df = df[~df["shed"]]

    interval_minutes = int((df["ts"].sort_values().diff().dropna().mode().iloc[0]).total_seconds() / 60)
    df["half_hour"] = ((df["ts"].dt.hour * 60 + df["ts"].dt.minute) // 30)
    df["dow"] = df["ts"].dt.dayofweek

    overall_mean = df["kw"].mean()
    generated_diurnal = (df.groupby("half_hour")["kw"].mean() / overall_mean).reindex(range(48)).to_numpy()
    generated_weekly = (df.groupby("dow")["kw"].mean() / overall_mean).reindex(range(7)).to_numpy()

    reference_diurnal = np.array(reference["diurnal_profile_by_half_hour"])
    reference_weekly = np.array(reference["weekly_profile_by_dow"])

    diurnal_corr = float(np.corrcoef(generated_diurnal, reference_diurnal)[0, 1])
    weekly_corr = float(np.corrcoef(generated_weekly, reference_weekly)[0, 1])

    # Per-connection load factor (mean/max over each connection's own
    # series), averaged -- comparable to the reference's single-household
    # figure without being swamped by aggregation-driven smoothing, which
    # would mechanically raise the load factor of any multi-connection sum.
    per_conn = df.groupby("connection_id")["kw"].agg(["mean", "max"])
    generated_load_factor = float((per_conn["mean"] / per_conn["max"]).mean())
    scenario_span_weeks = (df["ts"].max() - df["ts"].min()) / pd.Timedelta(weeks=1)
    reference_load_factor = _nearest_windowed_load_factor(reference, scenario_span_weeks)
    relative_error = abs(generated_load_factor - reference_load_factor) / reference_load_factor

    passes = (
        diurnal_corr >= min_correlation
        and weekly_corr >= min_correlation
        and relative_error <= max_load_factor_relative_error
    )

    return ShapeComparison(
        diurnal_correlation=diurnal_corr,
        weekly_correlation=weekly_corr,
        generated_load_factor=generated_load_factor,
        reference_load_factor=reference_load_factor,
        load_factor_relative_error=relative_error,
        n_connections=df["connection_id"].nunique(),
        n_intervals=df["ts"].nunique(),
        passes=passes,
        tolerance_notes=(
            f"thresholds: correlation >= {min_correlation}, "
            f"load factor relative error <= {max_load_factor_relative_error}. "
            "Compared against a SINGLE real household (UCI dataset), not a "
            "population -- see load_shapes.py docstring."
        ),
    )


@dataclass
class AnomalyCheck:
    connection_id: str
    anomaly_type: str
    recovered: bool
    detail: str


def check_anomaly_recoverability(session: Session, scenario_id: str) -> list[AnomalyCheck]:
    anomalies = session.execute(
        select(GroundTruthAnomaly).where(GroundTruthAnomaly.scenario_id == scenario_id)
    ).scalars().all()

    checks: list[AnomalyCheck] = []
    for anomaly in anomalies:
        rows = session.execute(
            select(
                GroundTruthConsumption.ts,
                GroundTruthConsumption.kw,
                GroundTruthConsumption.metered_kw,
            )
            .where(GroundTruthConsumption.scenario_id == scenario_id)
            .where(GroundTruthConsumption.connection_id == anomaly.connection_id)
            .order_by(GroundTruthConsumption.ts)
        ).all()
        df = pd.DataFrame(rows, columns=["ts", "kw", "metered_kw"])
        df["ts"] = pd.to_datetime(df["ts"])
        start = pd.Timestamp(anomaly.start_ts)
        if start.tzinfo is None and df["ts"].dt.tz is not None:
            start = start.tz_localize(df["ts"].dt.tz)

        before = df[df["ts"] < start]
        after = df[df["ts"] >= start]
        if before.empty or after.empty:
            checks.append(
                AnomalyCheck(anomaly.connection_id, anomaly.anomaly_type, False, "insufficient before/after data")
            )
            continue

        atype = AnomalyType(anomaly.anomaly_type)
        if atype in (AnomalyType.PARTIAL_BYPASS, AnomalyType.FULL_BYPASS, AnomalyType.METER_FAILURE):
            physical_ratio = after["kw"].mean() / max(before["kw"].mean(), 1e-9)
            metered_drop = 1 - (after["metered_kw"].mean() / max(before["metered_kw"].mean(), 1e-9))
            recovered = physical_ratio > 0.7 and metered_drop > 0.2
            detail = f"physical_ratio={physical_ratio:.2f}, metered_drop={metered_drop:.2f}"

        elif atype == AnomalyType.VACANCY:
            physical_drop = 1 - (after["kw"].mean() / max(before["kw"].mean(), 1e-9))
            recovered = physical_drop > 0.7
            detail = f"physical_drop={physical_drop:.2f}"

        elif atype == AnomalyType.SOLAR_ADOPTION:
            daylight_before = before[(before["ts"].dt.hour >= 9) & (before["ts"].dt.hour <= 15)]
            daylight_after = after[(after["ts"].dt.hour >= 9) & (after["ts"].dt.hour <= 15)]
            if daylight_before.empty or daylight_after.empty:
                recovered, detail = False, "no daylight-hour samples on one side"
            else:
                daylight_drop = 1 - (daylight_after["kw"].mean() / max(daylight_before["kw"].mean(), 1e-9))
                recovered = daylight_drop > 0.1
                detail = f"daylight_drop={daylight_drop:.2f}"
        else:
            recovered, detail = False, f"no check implemented for {atype}"

        checks.append(AnomalyCheck(anomaly.connection_id, anomaly.anomaly_type, recovered, detail))

    return checks
