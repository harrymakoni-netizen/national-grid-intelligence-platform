"""End-to-end generator test: build a scenario, persist it through the real
hierarchy schema, and check the things Section 15 actually asks for --
no orphaned records, upward aggregation correctness, and that the
association table reflects genuine (not artificially perfect) uncertainty.
"""
import pandas as pd
import pytest
from sqlalchemy import func, select

from gridintel.db.models import (
    Connection,
    ConnectionAssociation,
    GroundTruthAnomaly,
    GroundTruthConsumption,
    GroundTruthTechnicalLoss,
    NetworkNode,
    VendingEvent,
)
from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
from gridintel.hierarchy.aggregate import (
    aggregate_consumption_kw,
    descendant_ids,
    find_orphans,
    resolve_connections,
)


@pytest.fixture()
def generated_scenario(session):
    config = ScenarioConfig(
        substation_id="DS-INTEG",
        n_transformers=2,
        connections_per_transformer=12,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=2,
        interval_minutes=30,
    )
    scenario = generate_scenario(session, config, seed=99)
    session.commit()
    return scenario, config


def test_no_orphans_after_generation(session, generated_scenario):
    problems = find_orphans(session)
    assert problems == {"nodes": [], "associations": []}


def test_every_table_populated(session, generated_scenario):
    scenario, config = generated_scenario
    n_connections = config.n_transformers * config.connections_per_transformer

    assert session.execute(select(func.count()).select_from(Connection)).scalar() == n_connections
    assert (
        session.execute(select(func.count()).select_from(ConnectionAssociation)).scalar()
        == n_connections
    )
    assert session.execute(select(func.count()).select_from(GroundTruthConsumption)).scalar() > 0
    assert session.execute(select(func.count()).select_from(VendingEvent)).scalar() > 0
    assert session.execute(select(func.count()).select_from(GroundTruthAnomaly)).scalar() > 0
    assert session.execute(select(func.count()).select_from(GroundTruthTechnicalLoss)).scalar() > 0


def test_aggregation_upward_matches_sum_of_leaves(session, generated_scenario):
    scenario, config = generated_scenario
    ts = session.execute(
        select(GroundTruthConsumption.ts).limit(1)
    ).scalar()

    national_total = aggregate_consumption_kw(session, "NAT-ZW", scenario.id, ts)
    substation_total = aggregate_consumption_kw(session, config.substation_id, scenario.id, ts)
    assert national_total == pytest.approx(substation_total)

    transformer_ids = [
        nid for nid in descendant_ids(session, config.substation_id)
        if nid.startswith(f"{config.substation_id}-T")
    ]
    per_transformer_sum = sum(
        aggregate_consumption_kw(session, tid, scenario.id, ts) for tid in transformer_ids
    )
    assert per_transformer_sum == pytest.approx(substation_total)


def test_associations_are_not_artificially_perfect(session, generated_scenario):
    """The whole point of Section 11.1 is that recorded associations are
    sometimes wrong. If every synthetic association happened to be both
    correct and high-confidence, the generator would be hiding the exact
    problem the platform exists to solve.
    """
    scenario, config = generated_scenario
    associations = resolve_connections(session, config.substation_id)
    assert associations, "expected at least one resolved association"
    assert all(a.confidence < 1.0 for a in associations)
    assert all(a.source_type == "recorded" for a in associations)


def test_drill_down_resolves_from_root_to_individual_connection(session, generated_scenario):
    scenario, config = generated_scenario
    all_descendants = descendant_ids(session, "NAT-ZW")
    assert config.substation_id in all_descendants
    transformer_ids = [nid for nid in all_descendants if "-T" in nid and "-F" not in nid]
    assert len(transformer_ids) == config.n_transformers
