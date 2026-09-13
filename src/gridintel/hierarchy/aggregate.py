"""Hierarchy operations: validated construction, drill-down (descendants of
any node), roll-up (ancestors of any node), and confidence-aware resolution
of connections beneath a subtree.

This is the piece Section 5.1 calls "the single most important
data-engineering task in the project" -- aggregation must work upward from
any level and drill-down must resolve from any node to the leaves beneath
it, with no orphaned records.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from gridintel.db.models import (
    NODE_TYPE_ORDER,
    Connection,
    ConnectionAssociation,
    GroundTruthConsumption,
    NetworkNode,
    NodeType,
)


class HierarchyError(ValueError):
    pass


def _level(node_type: NodeType) -> int:
    return NODE_TYPE_ORDER.index(NodeType(node_type))


def validate_parent_child(parent_type: NodeType | None, child_type: NodeType) -> None:
    """Raise HierarchyError unless parent_type is exactly the predecessor
    level of child_type (or child_type is NATIONAL and parent_type is None).
    """
    child_type = NodeType(child_type)
    if child_type == NodeType.NATIONAL:
        if parent_type is not None:
            raise HierarchyError("NATIONAL node must have no parent")
        return
    if parent_type is None:
        raise HierarchyError(f"{child_type} node requires a parent")
    parent_type = NodeType(parent_type)
    if _level(parent_type) != _level(child_type) - 1:
        raise HierarchyError(
            f"invalid parent/child pair: {parent_type} cannot be the parent of {child_type}"
        )


def add_node(
    session: Session,
    *,
    id: str,
    node_type: NodeType,
    name: str,
    parent_id: str | None,
    latitude: float | None = None,
    longitude: float | None = None,
    attributes: dict | None = None,
) -> NetworkNode:
    """Insert a network node with level-ordering validated before it ever
    reaches the database, so a malformed tree cannot be constructed."""
    parent_type = None
    if parent_id is not None:
        parent = session.get(NetworkNode, parent_id)
        if parent is None:
            raise HierarchyError(f"parent node {parent_id!r} does not exist")
        parent_type = parent.node_type
    validate_parent_child(parent_type, node_type)
    node = NetworkNode(
        id=id,
        node_type=NodeType(node_type).value,
        name=name,
        parent_id=parent_id,
        latitude=latitude,
        longitude=longitude,
        attributes=attributes or {},
    )
    session.add(node)
    return node


def descendant_ids(session: Session, root_id: str) -> list[str]:
    """All node ids in the subtree rooted at root_id, including root_id
    itself, via a recursive CTE. Works identically on SQLite and Postgres.
    """
    base = select(NetworkNode.id, NetworkNode.parent_id).where(
        NetworkNode.id == root_id
    )
    cte = base.cte("descendants", recursive=True)
    nn = aliased(NetworkNode)
    recursive = select(nn.id, nn.parent_id).where(nn.parent_id == cte.c.id)
    cte = cte.union_all(recursive)
    rows = session.execute(select(cte.c.id)).scalars().all()
    return list(rows)


def ancestor_chain(session: Session, node_id: str) -> list[NetworkNode]:
    """The path from node_id up to the national root, inclusive, ordered
    root-first."""
    chain: list[NetworkNode] = []
    node = session.get(NetworkNode, node_id)
    if node is None:
        raise HierarchyError(f"node {node_id!r} does not exist")
    while node is not None:
        chain.append(node)
        node = session.get(NetworkNode, node.parent_id) if node.parent_id else None
    return list(reversed(chain))


@dataclass
class ResolvedConnection:
    connection_id: str
    network_node_id: str
    confidence: float
    source_type: str


def resolve_connections(
    session: Session,
    root_id: str,
    *,
    min_confidence: float = 0.0,
) -> list[ResolvedConnection]:
    """Every connection currently associated with a node in the subtree
    rooted at root_id, at or above min_confidence.

    Pass min_confidence=1.0 (or filter source_type == FIELD_CONFIRMED
    upstream) to get the "confirmed only" view; the default includes
    inferred associations, which is the "confirmed + inferred" view.
    Callers must choose explicitly and the chosen mode must be stated
    alongside any number this feeds into -- see Section 15's requirement
    that estimated and confirmed figures never be conflated silently.
    """
    node_ids = set(descendant_ids(session, root_id))
    stmt = (
        select(
            ConnectionAssociation.connection_id,
            ConnectionAssociation.network_node_id,
            ConnectionAssociation.confidence,
            ConnectionAssociation.source_type,
        )
        .where(ConnectionAssociation.effective_to.is_(None))
        .where(ConnectionAssociation.network_node_id.in_(node_ids))
        .where(ConnectionAssociation.confidence >= min_confidence)
    )
    return [
        ResolvedConnection(*row) for row in session.execute(stmt).all()
    ]


def set_association(
    session: Session,
    *,
    connection_id: str,
    network_node_id: str,
    confidence: float,
    source_type: str,
    evidence: dict | None = None,
    as_of: datetime | None = None,
) -> ConnectionAssociation:
    """Record a (possibly corrected) connection-to-transformer association.
    Closes out whatever was previously current for this connection and
    inserts a new current row -- corrections version forward, they never
    overwrite (Section 11.1).
    """
    if not (0.0 <= confidence <= 1.0):
        raise HierarchyError("confidence must be in [0, 1]")
    node = session.get(NetworkNode, network_node_id)
    if node is None:
        raise HierarchyError(f"network node {network_node_id!r} does not exist")
    if session.get(Connection, connection_id) is None:
        raise HierarchyError(f"connection {connection_id!r} does not exist")

    now = as_of or datetime.now(node.created_at.tzinfo)
    current = session.execute(
        select(ConnectionAssociation)
        .where(ConnectionAssociation.connection_id == connection_id)
        .where(ConnectionAssociation.effective_to.is_(None))
    ).scalar_one_or_none()
    if current is not None:
        current.effective_to = now

    new_assoc = ConnectionAssociation(
        connection_id=connection_id,
        network_node_id=network_node_id,
        confidence=confidence,
        source_type=source_type,
        effective_from=now,
        effective_to=None,
        evidence=evidence or {},
    )
    session.add(new_assoc)
    return new_assoc


def aggregate_consumption_kw(
    session: Session,
    root_id: str,
    scenario_id: str,
    ts: datetime,
    *,
    min_confidence: float = 0.0,
) -> float:
    """Sum of ground-truth consumption (kW) at a single timestamp across
    every connection resolved beneath root_id. Demonstrates and tests the
    "aggregation must work upward from any level" requirement: calling this
    at the transformer, the substation, or the national root must each
    equal the sum of the leaves beneath that respective level.
    """
    resolved = resolve_connections(session, root_id, min_confidence=min_confidence)
    conn_ids = [r.connection_id for r in resolved]
    if not conn_ids:
        return 0.0
    stmt = select(GroundTruthConsumption.kw).where(
        GroundTruthConsumption.scenario_id == scenario_id,
        GroundTruthConsumption.connection_id.in_(conn_ids),
        GroundTruthConsumption.ts == ts,
    )
    return float(sum(session.execute(stmt).scalars().all()))


def find_orphans(session: Session) -> dict[str, list[str]]:
    """Integrity check: nodes whose parent_id does not resolve, and current
    associations pointing at a node that does not exist. Should always
    return empty lists; used by tests and as an operational health check.
    """
    problems: dict[str, list[str]] = {"nodes": [], "associations": []}
    all_ids = set(session.execute(select(NetworkNode.id)).scalars().all())
    for node_id, parent_id in session.execute(
        select(NetworkNode.id, NetworkNode.parent_id)
    ).all():
        if parent_id is not None and parent_id not in all_ids:
            problems["nodes"].append(node_id)
    for assoc_id, node_id in session.execute(
        select(ConnectionAssociation.id, ConnectionAssociation.network_node_id).where(
            ConnectionAssociation.effective_to.is_(None)
        )
    ).all():
        if node_id not in all_ids:
            problems["associations"].append(str(assoc_id))
    return problems
