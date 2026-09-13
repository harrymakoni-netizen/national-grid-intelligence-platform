"""
Core schema for the network hierarchy, connection-transformer associations,
and synthetic ground-truth tables (Milestone 1, items 1-2).

Design notes:
- Generic SQLAlchemy types (JSON, Float, DateTime) are used throughout so the
  same models run against SQLite (fast local tests, no Docker required) and
  PostgreSQL/TimescaleDB (production). Postgres-only behaviour (hypertables)
  is applied in migrations, not in these model definitions.
- `NetworkNode` models the trusted MV/HV tree (national down to LV feeder).
  It is a real tree: one parent, enforced level ordering.
- The connection-to-transformer link is deliberately NOT a foreign key on
  `Connection`. It lives in `ConnectionAssociation` as a hypothesis with a
  confidence and a source, because Section 11.1 of the spec is explicit that
  this association is frequently missing or wrong and must never be treated
  as a known fact. Associations are versioned (effective_from/effective_to)
  rather than overwritten, so a correction never destroys history.
- Every synthetic ground-truth row carries a `scenario_id` back to
  `SyntheticScenario`, so no synthetic figure can ever be mistaken for a
  measured one downstream.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class NodeType(str, enum.Enum):
    NATIONAL = "national"
    REGION = "region"
    PRIMARY_SUBSTATION = "primary_substation"
    DISTRIBUTION_SUBSTATION = "distribution_substation"
    TRANSFORMER = "transformer"
    LV_FEEDER = "lv_feeder"


# The single source of truth for "what can be whose parent". Enforced in
# application code (see hierarchy.aggregate.validate_parent_child) rather
# than as a portable DB constraint, because expressing "parent.node_type
# must be the predecessor of child.node_type" as a CHECK constraint requires
# a self-join Postgres supports and SQLite does not.
NODE_TYPE_ORDER: list[NodeType] = [
    NodeType.NATIONAL,
    NodeType.REGION,
    NodeType.PRIMARY_SUBSTATION,
    NodeType.DISTRIBUTION_SUBSTATION,
    NodeType.TRANSFORMER,
    NodeType.LV_FEEDER,
]


class ConnectionArchetype(str, enum.Enum):
    HIGH_DENSITY_LOW_INCOME = "high_density_low_income"
    MEDIUM_DENSITY_RESIDENTIAL = "medium_density_residential"
    SMALL_COMMERCIAL = "small_commercial"
    INDUSTRIAL = "industrial"


class AssociationSource(str, enum.Enum):
    RECORDED = "recorded"
    INFERRED_CORRELATION = "inferred_correlation"
    FIELD_CONFIRMED = "field_confirmed"


class AnomalyType(str, enum.Enum):
    PARTIAL_BYPASS = "partial_bypass"
    FULL_BYPASS = "full_bypass"
    METER_FAILURE = "meter_failure"
    VACANCY = "vacancy"
    SOLAR_ADOPTION = "solar_adoption"


class NetworkNode(Base):
    """A node in the trusted MV/HV tree: national -> region -> primary
    substation -> distribution substation -> transformer -> LV feeder.

    This tree is assumed reliable (GIS / network records). The uncertain
    part of the hierarchy is one level down, in ConnectionAssociation.
    """

    __tablename__ = "network_node"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_type: Mapped[NodeType] = mapped_column(String(32), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_node.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Type-specific physical parameters: conductor length/rating for a
    # feeder, transformer rating/impedance/losses for a transformer, etc.
    # Kept schemaless here deliberately -- see gridsynth.topology for the
    # concrete keys each node_type is expected to carry.
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    parent: Mapped["NetworkNode | None"] = relationship(
        remote_side="NetworkNode.id", back_populates="children"
    )
    children: Mapped[list["NetworkNode"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_network_node_parent", "parent_id"),)


class Connection(Base):
    """A single metered customer connection (household, business, industrial)."""

    __tablename__ = "connection"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meter_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    archetype: Mapped[ConnectionArchetype] = mapped_column(String(32), nullable=False)
    tariff_band: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    associations: Mapped[list["ConnectionAssociation"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class ConnectionAssociation(Base):
    """Which transformer a connection is believed to sit beneath, with
    confidence and provenance. Never overwritten -- a correction closes out
    the previous row (effective_to) and inserts a new current one, so the
    full history of what we believed and when is preserved (Section 11.1).

    Association granularity is the transformer, not the LV feeder: a
    utility's low-voltage way-level records are rarely reliable enough to
    associate at that resolution, and correlation-based inference (shared
    outage/shedding timing) cannot distinguish feeders off the same
    transformer either. LV feeder topology exists in NetworkNode for
    power-flow purposes but connections are not asserted onto it.
    """

    __tablename__ = "connection_association"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connection.id"), nullable=False
    )
    network_node_id: Mapped[str] = mapped_column(
        ForeignKey("network_node.id"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_type: Mapped[AssociationSource] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Per-connection LV electrical placement -- distance along the service
    # drop and which of the three LV phases it is tapped to. Nullable
    # because this is exactly the kind of detail a bare "recorded" legacy
    # association usually lacks; it is populated once a field survey or
    # confirmation visit establishes it (Section 7.3). The digital twin
    # (Section 7) can only place a connection on its power-flow circuit
    # when this is known -- a connection with a transformer association but
    # no electrical placement is invisible to the twin's loss computation,
    # which is itself a real, reportable limitation, not an oversight.
    distance_from_transformer_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase: Mapped[int | None] = mapped_column(nullable=True)

    connection: Mapped["Connection"] = relationship(back_populates="associations")
    network_node: Mapped["NetworkNode"] = relationship()

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_confidence_range"),
        Index("ix_assoc_connection", "connection_id"),
        Index("ix_assoc_node", "network_node_id"),
        # Only one row per connection may be "current" (effective_to IS NULL).
        Index(
            "uq_assoc_current_per_connection",
            "connection_id",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
    )


class SyntheticScenario(Base):
    """A single reproducible generator run. Every synthetic ground-truth row
    in the tables below points back here, so no synthetic figure can ever be
    reported without its provenance and seed being traceable.
    """

    __tablename__ = "synthetic_scenario"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    seed: Mapped[int] = mapped_column(nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VendingEvent(Base):
    """A prepaid token purchase. Real production data lands here identically
    to synthetic data; `scenario_id` is NULL for real events and set for
    synthetic ones, which is the single flag that separates the two.
    """

    __tablename__ = "vending_event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connection.id"), nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(
        ForeignKey("synthetic_scenario.id"), nullable=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    kwh_purchased: Mapped[float] = mapped_column(Float, nullable=False)
    tariff_band: Mapped[str] = mapped_column(String(32), nullable=False)
    vending_channel: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_vending_connection_ts", "connection_id", "ts"),
        Index("ix_vending_scenario", "scenario_id"),
    )


class SensorReading(Base):
    """Device telemetry landing table (Layer 1). Empty in Milestone 1 -- no
    hardware exists yet -- but present so the ingestion path (MQTT ->
    validation -> storage) is identical for synthetic bench tests now and
    real devices later, per Section 11.2.
    """

    __tablename__ = "sensor_reading"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    network_node_id: Mapped[str] = mapped_column(
        ForeignKey("network_node.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    measurement: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_sensor_node_ts", "network_node_id", "ts"),)


class GroundTruthConsumption(Base):
    """True per-connection consumption as generated -- never observed in
    reality, only known because the generator constructed it.

    Two series are kept, because a bypass or meter failure makes them
    diverge and that divergence *is* the signal the platform exists to
    find:

    - `kw`: physical energy actually drawn, whether or not it is metered.
      This is what flows through the transformer and is what the digital
      twin's power-flow solution must balance against -- it is unaffected
      by meter bypass or failure (Section 8.2: "transformer-level load
      unchanged").
    - `metered_kw`: what the prepaid meter would register, which is what
      depletes the token balance and therefore what the purchasing
      simulation and Module A's reconstruction both operate on. Equal to
      `kw` for every connection with no active anomaly.
    """

    __tablename__ = "ground_truth_consumption"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("synthetic_scenario.id"), nullable=False
    )
    connection_id: Mapped[str] = mapped_column(ForeignKey("connection.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kw: Mapped[float] = mapped_column(Float, nullable=False)
    metered_kw: Mapped[float] = mapped_column(Float, nullable=False)
    shed: Mapped[bool] = mapped_column(nullable=False, default=False)

    __table_args__ = (
        Index("ix_gtc_scenario_connection_ts", "scenario_id", "connection_id", "ts"),
    )


class GroundTruthTechnicalLoss(Base):
    """Physically-computed technical loss (kW) per network node per
    interval, from the OpenDSS power-flow solution -- not an imposed
    percentage. Populated at transformer and feeder nodes.
    """

    __tablename__ = "ground_truth_technical_loss"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("synthetic_scenario.id"), nullable=False
    )
    network_node_id: Mapped[str] = mapped_column(
        ForeignKey("network_node.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    loss_kw: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_gttl_scenario_node_ts", "scenario_id", "network_node_id", "ts"),
    )


class ModelledTechnicalLoss(Base):
    """The digital twin's OWN estimate of technical loss (Section 7),
    computed from whatever consumption input and network knowledge the
    platform actually has -- never from privileged ground truth.

    This is distinct from GroundTruthTechnicalLoss, which only exists for
    synthetic scenarios and represents loss as it truly occurred. Comparing
    the two (scenario_id, network_node_id, ts all matching) is exactly
    Section 15's acceptance test for the twin. In production there is no
    ground-truth counterpart at all -- `scenario_id` is nullable for that
    reason -- and this table is the only "modelled technical loss" the
    platform has, becoming an input to loss attribution (Section 7.2)
    later.

    `coverage_fraction` records what proportion of connections associated
    with this transformer actually had a known electrical placement
    (distance + phase) and could be placed on the circuit. A twin result
    computed from partial coverage is expected to understate true loss --
    that gap is a real, informative signal about the completeness of the
    network hierarchy (Section 11.1), not a modelling error.
    """

    __tablename__ = "modelled_technical_loss"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[str | None] = mapped_column(
        ForeignKey("synthetic_scenario.id"), nullable=True
    )
    network_node_id: Mapped[str] = mapped_column(
        ForeignKey("network_node.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    loss_kw: Mapped[float] = mapped_column(Float, nullable=False)
    consumption_source: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_mtl_scenario_node_ts", "scenario_id", "network_node_id", "ts"),
    )


class GroundTruthAnomaly(Base):
    """A labelled anomaly injected at a known connection and known time --
    the ground truth Module B is evaluated against.
    """

    __tablename__ = "ground_truth_anomaly"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("synthetic_scenario.id"), nullable=False
    )
    connection_id: Mapped[str] = mapped_column(ForeignKey("connection.id"), nullable=False)
    anomaly_type: Mapped[AnomalyType] = mapped_column(String(32), nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_gta_scenario_connection", "scenario_id", "connection_id"),
    )
