from datetime import datetime, timezone

import pytest

from gridintel.db.models import Connection, ConnectionArchetype, NodeType
from gridintel.hierarchy.aggregate import (
    HierarchyError,
    add_node,
    aggregate_consumption_kw,
    ancestor_chain,
    descendant_ids,
    find_orphans,
    resolve_connections,
    set_association,
)
from gridintel.db.models import GroundTruthConsumption


def build_sample_tree(session):
    """national -> region -> primary_sub -> dist_sub -> {t1, t2} -> feeders

    t1 has 2 connections, t2 has 1 connection.
    """
    add_node(session, id="NAT", node_type=NodeType.NATIONAL, name="Zimbabwe", parent_id=None)
    add_node(session, id="REG1", node_type=NodeType.REGION, name="Harare Region", parent_id="NAT")
    add_node(
        session,
        id="PS1",
        node_type=NodeType.PRIMARY_SUBSTATION,
        name="Primary Sub 1",
        parent_id="REG1",
    )
    add_node(
        session,
        id="DS1",
        node_type=NodeType.DISTRIBUTION_SUBSTATION,
        name="Dist Sub 1",
        parent_id="PS1",
    )
    add_node(session, id="T1", node_type=NodeType.TRANSFORMER, name="Transformer 1", parent_id="DS1")
    add_node(session, id="T2", node_type=NodeType.TRANSFORMER, name="Transformer 2", parent_id="DS1")
    add_node(session, id="F1", node_type=NodeType.LV_FEEDER, name="Feeder 1", parent_id="T1")
    add_node(session, id="F2", node_type=NodeType.LV_FEEDER, name="Feeder 2", parent_id="T2")

    for cid in ("C1", "C2", "C3"):
        session.add(
            Connection(
                id=cid,
                customer_id=f"CUST-{cid}",
                meter_id=f"METER-{cid}",
                archetype=ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL.value,
                tariff_band="domestic",
            )
        )
    session.flush()

    set_association(
        session, connection_id="C1", network_node_id="T1", confidence=1.0,
        source_type="field_confirmed",
    )
    set_association(
        session, connection_id="C2", network_node_id="T1", confidence=0.6,
        source_type="inferred_correlation",
    )
    set_association(
        session, connection_id="C3", network_node_id="T2", confidence=1.0,
        source_type="recorded",
    )
    session.flush()


def test_invalid_parent_child_rejected(session):
    add_node(session, id="NAT", node_type=NodeType.NATIONAL, name="Zimbabwe", parent_id=None)
    with pytest.raises(HierarchyError):
        # a transformer cannot be a direct child of the national node
        add_node(session, id="BAD", node_type=NodeType.TRANSFORMER, name="Bad", parent_id="NAT")


def test_national_requires_no_parent(session):
    with pytest.raises(HierarchyError):
        add_node(session, id="X", node_type=NodeType.REGION, name="Orphan region", parent_id=None)


def test_descendant_ids_resolve_from_any_level(session):
    build_sample_tree(session)
    assert set(descendant_ids(session, "NAT")) == {
        "NAT", "REG1", "PS1", "DS1", "T1", "T2", "F1", "F2",
    }
    assert set(descendant_ids(session, "T1")) == {"T1", "F1"}
    assert set(descendant_ids(session, "F2")) == {"F2"}


def test_ancestor_chain(session):
    build_sample_tree(session)
    chain = [n.id for n in ancestor_chain(session, "F1")]
    assert chain == ["NAT", "REG1", "PS1", "DS1", "T1", "F1"]


def test_resolve_connections_respects_confidence_threshold(session):
    build_sample_tree(session)
    all_conns = resolve_connections(session, "NAT")
    assert {c.connection_id for c in all_conns} == {"C1", "C2", "C3"}

    confirmed_only = resolve_connections(session, "NAT", min_confidence=1.0)
    assert {c.connection_id for c in confirmed_only} == {"C1", "C3"}

    under_t1 = resolve_connections(session, "T1")
    assert {c.connection_id for c in under_t1} == {"C1", "C2"}


def test_association_correction_versions_not_overwrites(session):
    build_sample_tree(session)
    set_association(
        session, connection_id="C2", network_node_id="T2", confidence=0.9,
        source_type="field_confirmed", evidence={"note": "corrected after field visit"},
    )
    session.flush()

    current = resolve_connections(session, "NAT")
    c2_rows = [c for c in current if c.connection_id == "C2"]
    assert len(c2_rows) == 1
    assert c2_rows[0].network_node_id == "T2"
    assert c2_rows[0].confidence == 0.9

    from gridintel.db.models import ConnectionAssociation
    from sqlalchemy import select

    history = session.execute(
        select(ConnectionAssociation).where(ConnectionAssociation.connection_id == "C2")
    ).scalars().all()
    assert len(history) == 2
    closed = [h for h in history if h.effective_to is not None]
    assert len(closed) == 1
    assert closed[0].network_node_id == "T1"


def test_aggregation_matches_sum_of_leaves_at_every_level(session):
    build_sample_tree(session)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for cid, kw in (("C1", 0.5), ("C2", 0.3), ("C3", 1.2)):
        session.add(
            GroundTruthConsumption(
                scenario_id="scn-1", connection_id=cid, ts=ts, kw=kw,
                metered_kw=kw, shed=False,
            )
        )
    session.flush()

    assert aggregate_consumption_kw(session, "T1", "scn-1", ts) == pytest.approx(0.8)
    assert aggregate_consumption_kw(session, "T2", "scn-1", ts) == pytest.approx(1.2)
    assert aggregate_consumption_kw(session, "DS1", "scn-1", ts) == pytest.approx(2.0)
    assert aggregate_consumption_kw(session, "NAT", "scn-1", ts) == pytest.approx(2.0)

    # confirmed-only view excludes C2 (confidence 0.6), so T1's confirmed
    # total should drop to just C1.
    assert aggregate_consumption_kw(
        session, "T1", "scn-1", ts, min_confidence=1.0
    ) == pytest.approx(0.5)


def test_no_orphans_on_valid_tree(session):
    build_sample_tree(session)
    problems = find_orphans(session)
    assert problems == {"nodes": [], "associations": []}
