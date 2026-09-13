"""Module A tests (Section 8.1). These are written around the properties
that must hold regardless of how well any one connection reconstructs --
the hard bound, sane uncertainty behaviour -- plus a demonstrated case
where reconstruction beats a naive baseline (frequent-purchase archetypes)
and an honest acknowledgement of where it doesn't (see README and
evaluate.py's docstring for the sparse/bulk-purchase limitation).
"""
import numpy as np
import pandas as pd
import pytest

from gridintel.db.models import ConnectionArchetype
from gridintel.module_a.evaluate import (
    evaluate_against_held_out_real_data,
    evaluate_against_series,
    evaluate_scenario,
)
from gridintel.module_a.prior import population_shape_prior
from gridintel.module_a.reconstruct import reconstruct_for_connection, reconstruct_from_events
from gridintel.module_a.segment_reconstruction import run_segment_reconstruction
from gridintel.shedding_schedule import SheddingWindow


def test_prior_shape_has_unit_mean_and_responds_to_shedding():
    index = pd.date_range("2026-01-05", periods=48 * 14, freq="30min", tz="UTC")
    unshed = population_shape_prior(ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL, index)
    assert unshed.mean() == pytest.approx(1.0, rel=0.15)

    windows = [SheddingWindow(dow=d, start_hour=5, end_hour=9) for d in range(7)]
    shed = population_shape_prior(ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL, index, shedding_windows=windows)
    hours = index.hour
    shed_hours_mask = (hours >= 5) & (hours < 9)
    assert shed[shed_hours_mask].mean() < unshed[shed_hours_mask].mean()


def test_no_purchases_raises():
    index = pd.date_range("2026-01-01", periods=100, freq="30min", tz="UTC")
    prior = np.ones(100)
    with pytest.raises(ValueError):
        run_segment_reconstruction(index, prior, 30, np.zeros(100))


def test_hard_bound_never_violated_even_with_winsorization():
    """Every segment's reconstructed total must not exceed its funding
    purchase -- the property Section 8.1 requires, held by construction
    (winsorization only ever caps DOWNWARD, see segment_reconstruction.py).
    """
    rng = np.random.default_rng(0)
    index = pd.date_range("2026-01-01", periods=48 * 60, freq="30min", tz="UTC")
    prior = np.abs(rng.normal(1.0, 0.4, size=len(index)))

    purchase_by_interval = np.zeros(len(index))
    purchase_positions = sorted(rng.choice(len(index) - 1, size=10, replace=False))
    for pos in purchase_positions:
        purchase_by_interval[pos] = rng.uniform(5, 500)  # deliberately include large "stockpiling" purchases

    result = run_segment_reconstruction(index, prior, 30, purchase_by_interval)

    bounds = purchase_positions + [len(index)]
    for i, start in enumerate(purchase_positions):
        end = bounds[i + 1]
        segment_kwh = np.nansum(result.mean_kw[start:end]) * 0.5  # interval_hours
        assert segment_kwh <= purchase_by_interval[start] + 1e-6


def test_few_segments_produce_wider_uncertainty_than_many_consistent_ones():
    index = pd.date_range("2026-01-01", periods=48 * 60, freq="30min", tz="UTC")
    prior = np.ones(len(index))

    # Many purchases, all identical size/spacing -> low segment-to-segment variance.
    consistent = np.zeros(len(index))
    for pos in range(0, len(index) - 1, 48 * 5):
        consistent[pos] = 60.0
    consistent_result = run_segment_reconstruction(index, prior, 30, consistent)

    # Two purchases only -> too few segments to estimate spread confidently.
    sparse = np.zeros(len(index))
    sparse[10] = 500.0
    sparse[48 * 40] = 500.0
    sparse_result = run_segment_reconstruction(index, prior, 30, sparse)

    assert sparse_result.log_sigma >= consistent_result.log_sigma


def test_reconstruction_beats_naive_for_frequent_purchase_archetype(session):
    """High-density low-income connections buy small amounts frequently
    (weekly income cycle) -- the case this method is best suited to."""
    from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
    from gridintel.db.models import GroundTruthConsumption
    from sqlalchemy import select

    config = ScenarioConfig(
        substation_id="DS-MODA",
        n_transformers=1,
        connections_per_transformer=10,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=8,
        interval_minutes=30,
        archetype_mix={ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: 1.0},
    )
    scenario = generate_scenario(session, config, seed=21)
    session.commit()

    conn_id = "DS-MODA-T01-F1-C001"
    result = reconstruct_for_connection(
        session, conn_id, scenario.id, start=config.start, end=config.end, interval_minutes=30
    )
    rows = session.execute(
        select(GroundTruthConsumption.ts, GroundTruthConsumption.metered_kw)
        .where(GroundTruthConsumption.scenario_id == scenario.id)
        .where(GroundTruthConsumption.connection_id == conn_id)
    ).all()
    gt_df = pd.DataFrame(rows, columns=["ts", "metered_kw"])
    gt_df["ts"] = pd.to_datetime(gt_df["ts"]).dt.tz_localize("UTC")
    gt = gt_df.set_index("ts")["metered_kw"]
    recon = pd.Series(result.mean_kw, index=result.index)

    evaluation = evaluate_against_series(gt, recon)
    naive_mae = (gt - gt.mean()).abs().mean()
    assert evaluation.daily_mae < naive_mae


def test_evaluate_scenario_excludes_industrial_by_default(session):
    from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario

    config = ScenarioConfig(
        substation_id="DS-MODB",
        n_transformers=1,
        connections_per_transformer=15,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=6,
        interval_minutes=30,
    )
    scenario = generate_scenario(session, config, seed=22)
    session.commit()

    evaluation = evaluate_scenario(
        session, scenario.id, "DS-MODB-T01", start=config.start, end=config.end, interval_minutes=30
    )
    assert "industrial" in evaluation.excluded_archetypes
    assert evaluation.n_connections_evaluated > 0
    assert evaluation.aggregate.daily_mae >= 0


def test_evaluate_against_held_out_real_data_runs_and_returns_sane_bounds():
    """Section 12.2's methodology: real held-out interval data, simulated
    purchases, reconstruction compared to the REAL series. Testing this
    honestly surfaced that reconstruction quality on a single real
    household varies a lot by purchase-timing luck and does not always
    beat a naive constant-mean baseline (see README) -- this test checks
    the pipeline runs and produces sane, bounded output, not that it wins.
    """
    result = evaluate_against_held_out_real_data(seed=3)
    assert result.n_intervals > 1000
    assert result.daily_mae >= 0
    assert result.daily_relative_mae < 2.0  # sane bound: not wildly divergent
    assert 0.0 <= result.p10_p90_coverage <= 1.0
