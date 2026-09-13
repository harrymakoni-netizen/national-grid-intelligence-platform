"""Executes Section 15's acceptance criterion for the generator:

  "Generated load shapes are statistically indistinguishable from public
  reference data on diurnal profile, weekly pattern and load factor.
  Injected anomalies are recoverable by manual inspection of the ground
  truth."

If this test fails, the generator itself is not yet fit for use -- per the
build brief, downstream modules (A, B, the digital twin) cannot be
meaningfully developed against a generator that fails its own validation.
"""
import pandas as pd
import pytest

from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
from gridintel.gridsynth.validate import check_anomaly_recoverability, compare_to_reference_shape


@pytest.fixture(scope="module")
def validated_scenario_session():
    from gridintel.db.session import make_engine, make_session_factory
    from gridintel.db.models import Base

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        config = ScenarioConfig(
            substation_id="DS-ACCEPT",
            n_transformers=3,
            connections_per_transformer=15,
            start=pd.Timestamp("2026-01-05", tz="UTC"),
            weeks=4,
            interval_minutes=30,
        )
        scenario = generate_scenario(session, config, seed=2026)
        session.commit()
        yield session, scenario.id


def test_generated_shape_matches_public_reference(validated_scenario_session):
    session, scenario_id = validated_scenario_session
    comparison = compare_to_reference_shape(session, scenario_id)
    assert comparison.diurnal_correlation >= 0.85, comparison
    assert comparison.weekly_correlation >= 0.85, comparison
    assert comparison.load_factor_relative_error <= 0.5, comparison
    assert comparison.passes


def test_injected_anomalies_are_recoverable_from_ground_truth(validated_scenario_session):
    session, scenario_id = validated_scenario_session
    checks = check_anomaly_recoverability(session, scenario_id)
    assert len(checks) > 0
    failed = [c for c in checks if not c.recovered]
    assert not failed, f"anomalies not recoverable from their own ground truth: {failed}"
