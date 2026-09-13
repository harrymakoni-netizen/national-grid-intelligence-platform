"""Top-level generator entry point: generate_scenario() produces a
reproducible synthetic feeder -- topology, true and metered consumption,
vending events, injected anomalies and physically-computed technical loss
-- and persists all of it through the real hierarchy schema (Milestone 1
items 1 and 2 meeting at their intended join point).

Everything is seeded. The same (config, seed) always produces the same
scenario, which is what makes a scenario a usable, citable unit of ground
truth rather than a one-off run.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from gridintel.db.models import (
    AnomalyType,
    Connection,
    ConnectionArchetype,
    GroundTruthAnomaly,
    GroundTruthConsumption,
    GroundTruthTechnicalLoss,
    NetworkNode,
    NodeType,
    SyntheticScenario,
    VendingEvent,
)
from gridintel.gridsynth import __version__ as GENERATOR_VERSION
from gridintel.gridsynth.anomalies import inject_anomalies
from gridintel.gridsynth.archetypes import generate_true_consumption
from gridintel.gridsynth.lossmodel import compute_technical_losses
from gridintel.gridsynth.purchasing import generate_vending_events
from gridintel.gridsynth.shedding import (
    apply_shedding,
    assign_groups_to_transformers,
    generate_shedding_schedule,
)
from gridintel.gridsynth.topology import ARCHETYPE_MIX_DEFAULT, build_feeder_topology
from gridintel.hierarchy.aggregate import add_node, set_association

DEFAULT_ANOMALY_RATES = {
    AnomalyType.PARTIAL_BYPASS: 0.03,
    AnomalyType.FULL_BYPASS: 0.02,
    AnomalyType.METER_FAILURE: 0.02,
    AnomalyType.VACANCY: 0.03,
    AnomalyType.SOLAR_ADOPTION: 0.05,
}

# Records without field confirmation start at moderate confidence
# regardless of whether they happen to be correct -- correctness is not yet
# known to the system, only to the generator (Section 11.1).
UNCONFIRMED_RECORD_CONFIDENCE = 0.7
DEFAULT_WRONG_RECORD_RATE = 0.15


@dataclass
class ScenarioConfig:
    substation_id: str
    n_transformers: int = 2
    connections_per_transformer: int = 20
    start: pd.Timestamp = pd.Timestamp("2026-01-05", tz="UTC")
    weeks: int = 4
    interval_minutes: int = 15
    n_shedding_groups: int = 4
    archetype_mix: dict[ConnectionArchetype, float] = field(
        default_factory=lambda: dict(ARCHETYPE_MIX_DEFAULT)
    )
    anomaly_rates: dict[AnomalyType, float] = field(
        default_factory=lambda: dict(DEFAULT_ANOMALY_RATES)
    )
    # Fraction of connections whose recorded association points at the
    # wrong transformer (Section 11.1). Exposed as config -- not just a
    # module constant -- so the digital twin's validation can construct a
    # deliberately full-coverage scenario (rate=0) alongside the realistic
    # default, to isolate solver correctness from knowledge-completeness.
    wrong_record_rate: float = DEFAULT_WRONG_RECORD_RATE

    @property
    def end(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(weeks=self.weeks)

    def config_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["archetype_mix"] = {k.value: v for k, v in self.archetype_mix.items()}
        d["anomaly_rates"] = {k.value: v for k, v in self.anomaly_rates.items()}
        return d


def _scenario_id(config: ScenarioConfig, seed: int) -> str:
    digest = hashlib.sha256(f"{config.config_dict()}|{seed}".encode()).hexdigest()[:12]
    return f"scn-{config.substation_id}-{seed}-{digest}"


def _ensure_minimal_ancestor_chain(session: Session, substation_id: str) -> None:
    """Create a national -> region -> primary substation -> distribution
    substation chain above substation_id if it doesn't already exist, so
    generate_scenario can be run standalone (tests, demos) without
    requiring a separately-provisioned hierarchy.
    """
    from gridintel.db.models import NetworkNode

    if session.get(NetworkNode, substation_id) is not None:
        return

    national_id, region_id, primary_id = "NAT-ZW", f"REG-{substation_id}", f"PS-{substation_id}"
    if session.get(NetworkNode, national_id) is None:
        add_node(session, id=national_id, node_type=NodeType.NATIONAL, name="Zimbabwe", parent_id=None)
    if session.get(NetworkNode, region_id) is None:
        add_node(session, id=region_id, node_type=NodeType.REGION, name=f"Region ({substation_id})", parent_id=national_id)
    if session.get(NetworkNode, primary_id) is None:
        add_node(session, id=primary_id, node_type=NodeType.PRIMARY_SUBSTATION, name=f"Primary Substation ({substation_id})", parent_id=region_id)
    add_node(session, id=substation_id, node_type=NodeType.DISTRIBUTION_SUBSTATION, name=substation_id, parent_id=primary_id)
    session.flush()


def generate_scenario(session: Session, config: ScenarioConfig, *, seed: int) -> SyntheticScenario:
    scenario_id = _scenario_id(config, seed)
    rng = np.random.default_rng(seed)

    _ensure_minimal_ancestor_chain(session, config.substation_id)

    topology = build_feeder_topology(
        substation_id=config.substation_id,
        n_transformers=config.n_transformers,
        connections_per_transformer=config.connections_per_transformer,
        archetype_mix=config.archetype_mix,
        seed=seed,
    )

    for parent_id, node_id, node_type, name, attributes in topology.node_records:
        add_node(session, id=node_id, node_type=node_type, name=name, parent_id=parent_id, attributes=attributes)
    session.flush()

    tariff_band_by_archetype = {
        ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: "domestic_low",
        ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: "domestic",
        ConnectionArchetype.SMALL_COMMERCIAL: "commercial",
        ConnectionArchetype.INDUSTRIAL: "industrial",
    }
    archetype_by_connection: dict[str, ConnectionArchetype] = {}
    tariff_band_by_connection: dict[str, str] = {}
    transformer_by_connection: dict[str, str] = {}

    for conn in topology.connections:
        session.add(
            Connection(
                id=conn.connection_id,
                customer_id=f"CUST-{conn.connection_id}",
                meter_id=f"MTR-{conn.connection_id}",
                archetype=conn.archetype.value,
                tariff_band=tariff_band_by_archetype[conn.archetype],
            )
        )
        archetype_by_connection[conn.connection_id] = conn.archetype
        tariff_band_by_connection[conn.connection_id] = tariff_band_by_archetype[conn.archetype]
        transformer_by_connection[conn.connection_id] = conn.transformer_node_id
    session.flush()

    # Simulate realistic record imperfection: most associations start as
    # unverified "recorded" data at moderate confidence, and a configurable
    # fraction are simply wrong -- the true target is known here (by
    # construction) but not exposed to the association table itself.
    transformer_ids = [t.node_id for t in topology.transformers]
    for conn in topology.connections:
        is_wrong = rng.random() < config.wrong_record_rate and len(transformer_ids) > 1
        if is_wrong:
            wrong_choices = [t for t in transformer_ids if t != conn.transformer_node_id]
            assigned = str(rng.choice(wrong_choices))
        else:
            assigned = conn.transformer_node_id
        set_association(
            session,
            connection_id=conn.connection_id,
            network_node_id=assigned,
            confidence=UNCONFIRMED_RECORD_CONFIDENCE,
            source_type="recorded",
            evidence={"note": "synthetic scenario initial record", "scenario_id": scenario_id},
            # A wrong record carries no accompanying electrical survey --
            # nobody has confirmed this connection's placement, so its
            # distance/phase are simply unknown to the platform, not
            # fabricated to match the (wrong) transformer it's pinned to.
            # The digital twin can only place connections that are both
            # correctly associated AND have a known placement.
            distance_from_transformer_m=None if is_wrong else conn.distance_from_transformer_m,
            phase=None if is_wrong else conn.phase,
        )
    session.flush()

    true_consumption = generate_true_consumption(
        topology.connections,
        start=config.start,
        end=config.end,
        interval_minutes=config.interval_minutes,
        seed=seed,
    )

    shed_schedule = generate_shedding_schedule(config.n_shedding_groups, seed=seed)
    group_by_transformer = assign_groups_to_transformers(transformer_ids, config.n_shedding_groups, seed=seed)
    true_consumption = apply_shedding(
        true_consumption,
        transformer_by_connection=transformer_by_connection,
        group_by_transformer=group_by_transformer,
        schedule=shed_schedule,
    )

    # Persist shedding group + schedule -- otherwise this is generated,
    # used once to distort consumption, and thrown away, leaving nothing
    # for a downstream consumer (Module A) to condition on. A real
    # deployment would source the schedule from ZESA's published groups
    # (Section 9.1) rather than the generator, but the shape of what's
    # queryable should be the same either way.
    for transformer in topology.transformers:
        node = session.get(NetworkNode, transformer.node_id)
        node.attributes = {**node.attributes, "shedding_group": group_by_transformer[transformer.node_id]}
    shedding_schedule_json = {
        str(group): [{"dow": w.dow, "start_hour": w.start_hour, "end_hour": w.end_hour} for w in windows]
        for group, windows in shed_schedule.items()
    }

    with_anomalies, anomaly_records = inject_anomalies(
        true_consumption,
        topology.connections,
        start=config.start,
        end=config.end,
        interval_minutes=config.interval_minutes,
        rates=config.anomaly_rates,
        seed=seed,
    )

    metered_input = with_anomalies[["connection_id", "ts", "metered_kw"]].rename(
        columns={"metered_kw": "kw"}
    )
    final_consumption, vending_events = generate_vending_events(
        metered_input,
        archetype_by_connection,
        tariff_band_by_connection,
        interval_minutes=config.interval_minutes,
        seed=seed,
    )
    # final_consumption['kw'] here is post-balance-exhaustion METERED
    # consumption. Physical consumption (for loss/twin purposes) is
    # unaffected by prepaid balance -- a bypass victim's physical draw
    # doesn't stop because a legitimate meter would have self-disconnected.
    physical = with_anomalies[["connection_id", "ts", "kw", "shed"]].rename(columns={"kw": "kw_physical"})
    metered = final_consumption.rename(columns={"kw": "metered_kw_final"})
    merged = physical.merge(metered, on=["connection_id", "ts"], how="left")

    gtc_rows = [
        {
            "scenario_id": scenario_id,
            "connection_id": r.connection_id,
            "ts": r.ts.to_pydatetime(),
            "kw": float(r.kw_physical),
            "metered_kw": float(r.metered_kw_final),
            "shed": bool(r.shed),
        }
        for r in merged.itertuples(index=False)
    ]
    session.execute(GroundTruthConsumption.__table__.insert(), gtc_rows)

    vending_rows = [
        {
            "connection_id": r.connection_id,
            "scenario_id": scenario_id,
            "ts": r.ts.to_pydatetime(),
            "amount": float(r.amount),
            "currency": r.currency,
            "kwh_purchased": float(r.kwh_purchased),
            "tariff_band": r.tariff_band,
            "vending_channel": r.vending_channel,
        }
        for r in vending_events.itertuples(index=False)
    ]
    if vending_rows:
        session.execute(VendingEvent.__table__.insert(), vending_rows)

    anomaly_rows = [
        {
            "scenario_id": scenario_id,
            "connection_id": rec.connection_id,
            "anomaly_type": rec.anomaly_type.value,
            "start_ts": rec.start_ts.to_pydatetime(),
            "end_ts": rec.end_ts.to_pydatetime() if rec.end_ts is not None else None,
            "parameters": rec.parameters,
        }
        for rec in anomaly_records
    ]
    if anomaly_rows:
        session.execute(GroundTruthAnomaly.__table__.insert(), anomaly_rows)

    # A vacated premises is, per Section 8.2, usually reflected "in most
    # cases" by a corresponding customer-system record -- a real Tier 1
    # signal Module B can use directly, rather than only inferring vacancy
    # from consumption behaviour. Not set for other anomaly types: bypass,
    # meter failure and solar adoption all involve an occupied premises
    # with an ostensibly still-active account, which is exactly what makes
    # them hard to tell apart from vacancy on consumption data alone.
    vacant_connection_ids = [
        rec.connection_id for rec in anomaly_records if rec.anomaly_type == AnomalyType.VACANCY
    ]
    if vacant_connection_ids:
        session.execute(
            Connection.__table__.update()
            .where(Connection.id.in_(vacant_connection_ids))
            .values(status="inactive")
        )

    loss_df = compute_technical_losses(
        topology,
        physical.rename(columns={"kw_physical": "kw"})[["connection_id", "ts", "kw"]],
        seed=seed,
    )
    loss_rows = [
        {
            "scenario_id": scenario_id,
            "network_node_id": r.network_node_id,
            "ts": r.ts.to_pydatetime(),
            "loss_kw": float(r.loss_kw),
        }
        for r in loss_df.itertuples(index=False)
    ]
    if loss_rows:
        session.execute(GroundTruthTechnicalLoss.__table__.insert(), loss_rows)

    scenario = SyntheticScenario(
        id=scenario_id,
        name=f"Synthetic feeder {config.substation_id} seed={seed}",
        seed=seed,
        config={**config.config_dict(), "shedding_schedule_by_group": shedding_schedule_json},
        generator_version=GENERATOR_VERSION,
    )
    session.add(scenario)
    session.flush()
    return scenario
