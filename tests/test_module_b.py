"""Module B tests (Section 8.2). Weak-supervision unit tests use hand-built
ConnectionFeatures so they're fast and deterministic and pin the exact
bugs found and fixed while building this against real synthetic data
(vote-splitting, the solar evening-gate, and the vacancy purchase-activity
gate -- see weak_supervision.py's docstrings for the mechanism of each).
The end-to-end test uses a real generated scenario and checks the
directional property Section 8.2 itself says matters: precision at the
top of the ranked list should be well above precision across the whole
queue, because inspector capacity is the binding constraint.
"""
import pandas as pd
import pytest

from gridintel.db.models import AnomalyType
from gridintel.module_b.features import ConnectionFeatures
from gridintel.module_b.weak_supervision import NORMAL, classify


def _features(**overrides) -> ConnectionFeatures:
    defaults = dict(
        connection_id="C1",
        baseline_mean_kw=1.0,
        recent_mean_kw=1.0,
        fractional_change=0.0,
        daylight_fractional_change=0.0,
        evening_fractional_change=0.0,
        irradiance_correlation=0.0,
        step_sharpness=0.0,
        zero_purchase_activity_recent=False,
        connection_inactive=False,
        open_segment_ratio=0.0,
        peer_group_z_score=0.0,
    )
    defaults.update(overrides)
    return ConnectionFeatures(**defaults)


def test_clear_solar_signature_classified_as_solar():
    f = _features(
        daylight_fractional_change=-0.6,
        irradiance_correlation=-0.7,
        evening_fractional_change=-0.05,  # preserved
        fractional_change=-0.4,
    )
    label = classify(f)
    assert label.predicted_cause == AnomalyType.SOLAR_ADOPTION.value


def test_total_collapse_not_misclassified_as_solar():
    """The bug this pins: evening collapsing as much as daylight is NOT
    solar (without storage), even when Module A reconstruction noise
    produces a spuriously negative irradiance correlation.
    """
    f = _features(
        daylight_fractional_change=-0.92,
        evening_fractional_change=-0.96,  # collapsed just as much -- not preserved
        irradiance_correlation=-0.43,  # spurious, from noise
        fractional_change=-0.94,
        connection_inactive=True,
    )
    label = classify(f)
    assert label.predicted_cause != AnomalyType.SOLAR_ADOPTION.value


def test_inactive_status_alone_is_enough_for_vacancy():
    """The bug this pins: requiring zero_purchase_activity_recent as a hard
    AND-gate excluded real vacancy cases where a habitual top-up still
    landed in the recent window on calendar timing alone.
    """
    f = _features(connection_inactive=True, fractional_change=-0.9, zero_purchase_activity_recent=False)
    label = classify(f)
    assert label.predicted_cause == AnomalyType.VACANCY.value


def test_ambiguous_failure_bypass_split_beats_single_cause_with_less_evidence():
    """The bug this pins: a flat plurality vote let 'normal' (single vote,
    0.6) beat a genuinely ambiguous meter_failure/full_bypass split (0.5 +
    0.5 = 1.0 total anomaly evidence) purely because the anomaly evidence
    was divided across two labels. The two-stage combiner (anomalous-or-not
    first, which cause second) must not have this failure mode.
    """
    f = _features(fractional_change=-0.9, step_sharpness=3.0, open_segment_ratio=0.0, peer_group_z_score=-0.5)
    label = classify(f)
    assert label.predicted_cause in {AnomalyType.METER_FAILURE.value, AnomalyType.FULL_BYPASS.value}
    assert label.predicted_cause != NORMAL


def test_genuine_reduction_not_flagged():
    f = _features(fractional_change=-0.15, peer_group_z_score=0.2)
    label = classify(f)
    assert label.predicted_cause == NORMAL


def test_case_queue_precision_at_top_beats_precision_over_full_queue(session):
    """Section 8.2: "the operative metric is precision at the top of the
    ranked list ... because inspector capacity is the binding constraint."
    This is the property that must hold, not any specific number -- exact
    precision is inherently seed-dependent with only a handful of ground-
    truth anomalies per scenario.
    """
    from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
    from gridintel.module_b.pipeline import build_case_queue
    from gridintel.module_b.evaluate import evaluate_case_queue

    config = ScenarioConfig(
        substation_id="DS-MODB2",
        n_transformers=2,
        connections_per_transformer=20,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=8,
        interval_minutes=30,
    )
    scenario = generate_scenario(session, config, seed=25)
    session.commit()

    all_entries = []
    for tid in ["DS-MODB2-T01", "DS-MODB2-T02"]:
        all_entries.extend(
            build_case_queue(session, tid, scenario.id, start=config.start, end=config.end, interval_minutes=30)
        )
    all_entries.sort(key=lambda e: (e.confidence, e.suspicion_score), reverse=True)

    top_3 = evaluate_case_queue(session, scenario.id, all_entries, k=3)
    full_queue = evaluate_case_queue(session, scenario.id, all_entries)

    assert top_3.n_cases > 0
    assert top_3.confusable_aware_precision >= full_queue.confusable_aware_precision


def test_nontechnical_loss_residual_is_small_under_full_coverage(session):
    """Section 7.2's equation, sanity-checked: with a single transformer
    (no wrong associations possible -- Section 11.1's corruption needs a
    second transformer to reassign to) and therefore full coverage, the
    residual should be small relative to the transformer's own scale --
    it should reflect Module A/twin estimation noise, not a large
    systematic gap.
    """
    from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
    from gridintel.module_b.nontechnical_loss import compute_nontechnical_loss

    config = ScenarioConfig(
        substation_id="DS-MODB3",
        n_transformers=1,
        connections_per_transformer=15,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=6,
        interval_minutes=30,
    )
    scenario = generate_scenario(session, config, seed=7)
    session.commit()

    result = compute_nontechnical_loss(
        session, scenario.id, "DS-MODB3-T01", start=config.start, end=config.end, interval_minutes=30
    )
    assert result.twin_coverage_fraction == pytest.approx(1.0)
    assert len(result.series) > 0
    assert abs(result.series.mean()) < 0.2 * result.measured_inflow_kw.mean()
