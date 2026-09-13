"""Section 8.1's evaluation methodology, made executable:

  "Evaluated on held-out interval-metered customers by mean absolute error
  at daily and monthly resolution, and by calibration of the predicted
  uncertainty. The aggregate estimate at transformer level is the
  operationally important quantity and is materially more accurate than
  any individual customer estimate, because errors are largely independent
  across customers."

Two evaluation paths:

1. evaluate_against_series(): a generic comparison (MAE at daily/monthly
   resolution, p10-p90 coverage) between a reconstruction and any ground
   truth series -- synthetic or real.

2. evaluate_against_held_out_real_data(): Section 12.2's specific
   methodology -- take the REAL held-out interval sample (the last 90 days
   of the UCI household, never used to fit anything), simulate prepaid
   purchase events from it, reconstruct, and compare against the REAL
   consumption. This is the one evaluation in this module that involves no
   synthetic consumption at all; only the purchase-generation step is
   invented, exactly as flagged in gridsynth/purchasing.py.

A real, load-bearing finding from testing this module (see also README):
reconstruction works materially better for frequent-small-purchase
archetypes (high/medium density residential) than for infrequent-bulk-
purchase ones (small commercial, industrial). This is not a tuning gap --
few, large purchases genuinely carry less information about within-segment
timing, and real industrial/commercial customers are, per Section 3.1, the
segment most likely to already have post-paid interval metering and
therefore the segment LEAST in need of purchase-based reconstruction in
production. evaluate_scenario()'s `exclude_archetypes` default reflects this.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import Connection, ConnectionArchetype, GroundTruthConsumption
from gridintel.gridsynth.purchasing import simulate_connection
from gridintel.module_a.reconstruct import reconstruct_for_connection, reconstruct_from_events

HELD_OUT_PATH = Path(__file__).resolve().parents[3] / "data" / "processed" / "held_out_interval_sample.csv"


@dataclass
class SeriesEvaluation:
    n_intervals: int
    daily_mae: float
    monthly_mae: float
    daily_relative_mae: float
    p10_p90_coverage: float  # fraction of true values falling within [p10, p90]; target ~0.80


def evaluate_against_series(
    ground_truth_kw: pd.Series,
    recon_mean_kw: pd.Series,
    recon_p10_kw: pd.Series | None = None,
    recon_p90_kw: pd.Series | None = None,
) -> SeriesEvaluation:
    df = pd.concat(
        [ground_truth_kw.rename("gt"), recon_mean_kw.rename("recon")], axis=1, sort=True
    ).dropna()
    if len(df) == 0:
        raise ValueError("no overlapping intervals between ground truth and reconstruction")

    daily = df.resample("1D").mean()
    monthly = df.resample("MS").mean()
    daily_mae = float((daily["gt"] - daily["recon"]).abs().mean())
    monthly_mae = float((monthly["gt"] - monthly["recon"]).abs().mean())
    daily_relative_mae = daily_mae / max(daily["gt"].mean(), 1e-9)

    coverage = float("nan")
    if recon_p10_kw is not None and recon_p90_kw is not None:
        band = pd.concat(
            [ground_truth_kw.rename("gt"), recon_p10_kw.rename("p10"), recon_p90_kw.rename("p90")], axis=1, sort=True
        ).dropna()
        if len(band) > 0:
            coverage = float(((band["gt"] >= band["p10"]) & (band["gt"] <= band["p90"])).mean())

    return SeriesEvaluation(
        n_intervals=len(df),
        daily_mae=daily_mae,
        monthly_mae=monthly_mae,
        daily_relative_mae=daily_relative_mae,
        p10_p90_coverage=coverage,
    )


@dataclass
class ScenarioEvaluation:
    n_connections_evaluated: int
    n_connections_skipped_no_purchases: int
    per_connection: dict[str, SeriesEvaluation]
    aggregate: SeriesEvaluation
    excluded_archetypes: list[str]


def evaluate_scenario(
    session: Session,
    scenario_id: str,
    transformer_id_prefix: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
    exclude_archetypes: tuple[ConnectionArchetype, ...] = (ConnectionArchetype.INDUSTRIAL,),
) -> ScenarioEvaluation:
    """Evaluates every connection whose id starts with transformer_id_prefix
    both individually and as a transformer-level aggregate -- the
    comparison Section 8.1 explicitly says matters most.
    """
    connections = [
        c
        for c in session.execute(select(Connection)).scalars()
        if c.id.startswith(transformer_id_prefix)
        and ConnectionArchetype(c.archetype) not in exclude_archetypes
    ]

    per_connection: dict[str, SeriesEvaluation] = {}
    recon_series: dict[str, pd.Series] = {}
    gt_series: dict[str, pd.Series] = {}
    n_skipped = 0

    for conn in connections:
        try:
            result = reconstruct_for_connection(
                session, conn.id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
            )
        except ValueError:
            n_skipped += 1
            continue

        rows = session.execute(
            select(GroundTruthConsumption.ts, GroundTruthConsumption.metered_kw)
            .where(GroundTruthConsumption.scenario_id == scenario_id)
            .where(GroundTruthConsumption.connection_id == conn.id)
        ).all()
        gt_df = pd.DataFrame(rows, columns=["ts", "metered_kw"])
        gt_df["ts"] = pd.to_datetime(gt_df["ts"]).dt.tz_localize(result.index.tz)
        gt = gt_df.set_index("ts")["metered_kw"]

        recon = pd.Series(result.mean_kw, index=result.index)
        recon_series[conn.id] = recon
        gt_series[conn.id] = gt
        per_connection[conn.id] = evaluate_against_series(gt, recon)

    if not recon_series:
        raise ValueError(f"no connections with purchase history found under prefix {transformer_id_prefix!r}")

    recon_sum = pd.concat(recon_series.values(), axis=1).sum(axis=1)
    gt_sum = pd.concat(gt_series.values(), axis=1).sum(axis=1)
    aggregate = evaluate_against_series(gt_sum, recon_sum)

    return ScenarioEvaluation(
        n_connections_evaluated=len(recon_series),
        n_connections_skipped_no_purchases=n_skipped,
        per_connection=per_connection,
        aggregate=aggregate,
        excluded_archetypes=[a.value for a in exclude_archetypes],
    )


def evaluate_against_held_out_real_data(
    archetype: ConnectionArchetype = ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL,
    *,
    seed: int = 0,
) -> SeriesEvaluation:
    """Section 12.2's methodology: real held-out interval consumption (the
    UCI household's last 90 days, never used to fit anything) drives a
    simulated purchase history, which Module A then has to invert. The
    comparison target is the REAL consumption, not a synthetic one.
    """
    if not HELD_OUT_PATH.exists():
        raise FileNotFoundError(f"{HELD_OUT_PATH} not found. Run scripts/process_public_dataset.py first.")

    held_out = pd.read_csv(HELD_OUT_PATH, index_col=0, parse_dates=True)
    true_kw = held_out["kw"].to_numpy()
    index = pd.DatetimeIndex(held_out.index).tz_localize("UTC")
    interval_minutes = int(round((index[1] - index[0]).total_seconds() / 60))

    _, events = simulate_connection(
        connection_id="held-out-real",
        archetype=archetype,
        tariff_band="domestic",
        true_kw=true_kw,
        timestamps=index,
        interval_minutes=interval_minutes,
        seed=seed,
    )
    events_df = pd.DataFrame(
        [{"ts": e.ts, "kwh_purchased": e.kwh_purchased} for e in events]
    )

    result = reconstruct_from_events(
        events_df,
        archetype,
        start=index[0],
        end=index[-1] + pd.Timedelta(minutes=interval_minutes),
        interval_minutes=interval_minutes,
    )
    recon = pd.Series(result.mean_kw, index=result.index)
    gt = pd.Series(true_kw, index=index)

    return evaluate_against_series(gt, recon, pd.Series(result.p10_kw, index=result.index), pd.Series(result.p90_kw, index=result.index))
