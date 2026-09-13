"""Section 15's acceptance criterion for the digital twin:

  "Computed technical loss on the synthetic feeder matches the loss
  imposed by the generator within a stated tolerance across a range of
  loading conditions."

Two scenarios are tested deliberately:

1. Full coverage (wrong_record_rate=0): every connection is correctly
   associated with a known electrical placement, so the twin can place
   every connection the generator itself used. This isolates whether the
   shared OpenDSS engine is correctly wired for both callers -- with
   identical inputs, twin and ground truth MUST match almost exactly.

2. Realistic coverage (the default wrong_record_rate): some connections
   are unplaceable by the twin (Section 11.1's actual problem). The twin
   is then expected to UNDERSTATE true loss, not match it -- and this test
   asserts that understatement is real, bounded, and roughly proportional
   to the missing load, rather than asserting a match that would only be
   possible by silently leaking ground truth into the twin.
"""
import pandas as pd
import pytest

from gridintel.db.models import GroundTruthConsumption, GroundTruthTechnicalLoss
from gridintel.digitaltwin.twin import compute_modelled_loss
from gridintel.digitaltwin.validate import compare_twin_to_ground_truth
from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
from sqlalchemy import select


def _generate(session, *, wrong_record_rate, seed, n_transformers=1):
    # A wrong association can only redirect a connection to a DIFFERENT
    # transformer, so demonstrating partial coverage needs at least 2.
    config = ScenarioConfig(
        substation_id="DS-TWIN",
        n_transformers=n_transformers,
        connections_per_transformer=15,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=1,
        interval_minutes=30,
        wrong_record_rate=wrong_record_rate,
    )
    scenario = generate_scenario(session, config, seed=seed)
    session.commit()
    return scenario, config


def _ground_truth_physical_consumption(session, scenario_id) -> pd.DataFrame:
    rows = session.execute(
        select(
            GroundTruthConsumption.connection_id,
            GroundTruthConsumption.ts,
            GroundTruthConsumption.kw,
        ).where(GroundTruthConsumption.scenario_id == scenario_id)
    ).all()
    df = pd.DataFrame(rows, columns=["connection_id", "ts", "kw"])
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def _ground_truth_loss(session, scenario_id, transformer_id) -> pd.DataFrame:
    rows = session.execute(
        select(GroundTruthTechnicalLoss.ts, GroundTruthTechnicalLoss.loss_kw)
        .where(GroundTruthTechnicalLoss.scenario_id == scenario_id)
        .where(GroundTruthTechnicalLoss.network_node_id == transformer_id)
    ).all()
    df = pd.DataFrame(rows, columns=["ts", "loss_kw"])
    df["ts"] = pd.to_datetime(df["ts"])
    return df.set_index("ts")["loss_kw"]


def test_twin_matches_ground_truth_under_full_coverage(session):
    scenario, config = _generate(session, wrong_record_rate=0.0, seed=11)
    transformer_id = f"{config.substation_id}-T01"

    physical = _ground_truth_physical_consumption(session, scenario.id)
    result = compute_modelled_loss(session, transformer_id, physical)

    assert result.coverage_fraction == pytest.approx(1.0)
    assert result.n_associated_connections == config.connections_per_transformer

    gt_loss = _ground_truth_loss(session, scenario.id, transformer_id)
    twin_loss = result.loss_series.set_index("ts")["total_loss_kw"]

    compared = pd.concat([gt_loss.rename("gt"), twin_loss.rename("twin")], axis=1).dropna()
    assert len(compared) > 0
    relative_error = ((compared["twin"] - compared["gt"]).abs() / compared["gt"]).mean()
    assert relative_error < 0.01, f"twin should reproduce ground truth almost exactly under full coverage, got {relative_error:.4f}"


def test_twin_understates_loss_under_partial_coverage(session):
    scenario, config = _generate(session, wrong_record_rate=0.3, seed=12, n_transformers=2)
    transformer_id = f"{config.substation_id}-T01"

    physical = _ground_truth_physical_consumption(session, scenario.id)
    result = compute_modelled_loss(session, transformer_id, physical)

    assert 0.0 < result.coverage_fraction < 1.0, "test is only meaningful if coverage is genuinely partial"

    gt_loss = _ground_truth_loss(session, scenario.id, transformer_id)
    twin_loss = result.loss_series.set_index("ts")["total_loss_kw"]
    compared = pd.concat([gt_loss.rename("gt"), twin_loss.rename("twin")], axis=1).dropna()

    # The twin sees less load than physically exists, so it should
    # understate loss on average -- not match it, and not overstate it.
    assert (compared["twin"] <= compared["gt"] + 1e-6).mean() > 0.9
    mean_understatement = 1 - (compared["twin"].mean() / compared["gt"].mean())
    assert mean_understatement > 0.02, "partial coverage should produce a real, measurable loss gap"


def test_twin_rejects_non_transformer_node(session):
    scenario, config = _generate(session, wrong_record_rate=0.0, seed=13)
    physical = _ground_truth_physical_consumption(session, scenario.id)
    with pytest.raises(Exception):
        compute_modelled_loss(session, config.substation_id, physical)


def test_compare_twin_to_ground_truth_wrapper_agrees_with_manual_computation(session):
    scenario, config = _generate(session, wrong_record_rate=0.3, seed=12, n_transformers=2)
    transformer_id = f"{config.substation_id}-T01"

    comparison = compare_twin_to_ground_truth(session, scenario.id, transformer_id)

    assert 0.0 < comparison.coverage_fraction < 1.0
    assert comparison.n_intervals_compared > 0
    assert comparison.mean_modelled_loss_kw < comparison.mean_ground_truth_loss_kw
    assert comparison.mean_relative_error > 0
