"""Synthetic feeder topology: one distribution substation feeding several
distribution transformers, each with a star of LV service-drop laterals to
individual connections.

Physical parameters (conductor R/X, transformer impedance and loss split)
come from gridintel.network_catalog and are REPRESENTATIVE values for a
typical 400V African LV network, not ZETDC-specific measurements -- see
that module for the PLACEHOLDER markers, sourcing notes, and the star- vs
trunk-topology limitation. Confirm against a real feeder survey or ZETDC
network records, and have the power-systems engineer (Section 14.1) review
before this topology generator's output is used beyond internal development.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from gridintel.db.models import ConnectionArchetype, NodeType
from gridintel.network_catalog import (
    LV_FEEDER_R_OHM_PER_KM,
    LV_FEEDER_X_OHM_PER_KM,
    LV_KV,
    MV_KV,
    SERVICE_DROP_R_OHM_PER_KM,
    SERVICE_DROP_X_OHM_PER_KM,
    TRANSFORMER_CATALOG,
)

ARCHETYPE_MIX_DEFAULT = {
    ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: 0.45,
    ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: 0.35,
    ConnectionArchetype.SMALL_COMMERCIAL: 0.15,
    ConnectionArchetype.INDUSTRIAL: 0.05,
}


@dataclass
class TransformerSpec:
    node_id: str
    rating_kva: float
    no_load_loss_kw: float
    load_loss_kw: float
    impedance_pct: float
    vector_group: str = "Dyn11"


@dataclass
class ConnectionSpec:
    connection_id: str
    transformer_node_id: str
    lv_feeder_node_id: str
    archetype: ConnectionArchetype
    distance_from_transformer_m: float
    service_drop_r_ohm: float
    service_drop_x_ohm: float
    # Which of the 3 LV phases this connection is single-phase-tapped to.
    # Fixed once at topology construction -- this MUST be a stable,
    # persisted property (not re-derived per loss computation), or the
    # generator's own ground-truth loss and the digital twin's later
    # re-solve of the same circuit could silently disagree about which
    # phase carries which load.
    phase: int


@dataclass
class FeederTopology:
    substation_node_id: str
    transformers: list[TransformerSpec] = field(default_factory=list)
    connections: list[ConnectionSpec] = field(default_factory=list)
    # (parent_id, node_id, node_type, name, attributes) tuples ready to be
    # inserted via hierarchy.aggregate.add_node, in an order that respects
    # level ordering (substation -> transformer -> lv_feeder).
    node_records: list[tuple[str | None, str, NodeType, str, dict]] = field(
        default_factory=list
    )


def _pick_rating_kva(n_connections: int, rng: np.random.Generator) -> float:
    """Rough sizing heuristic: enough headroom for coincident peak plus
    margin, rounded to a catalog size. This is a planning heuristic, not a
    load-flow-verified sizing -- real sizing is a Section 7 twin question.
    """
    assumed_kw_per_connection_diversified = rng.uniform(0.3, 0.5)
    est_kva = n_connections * assumed_kw_per_connection_diversified / 0.9
    for rating in sorted(TRANSFORMER_CATALOG):
        if rating >= est_kva:
            return float(rating)
    return float(max(TRANSFORMER_CATALOG))


def build_feeder_topology(
    *,
    substation_id: str,
    n_transformers: int,
    connections_per_transformer: int,
    archetype_mix: dict[ConnectionArchetype, float] | None = None,
    seed: int,
) -> FeederTopology:
    """Generate a configurable feeder: one distribution substation, N
    transformers, one LV feeder per transformer, and a star of service-drop
    laterals to individual connections distributed by archetype mix.
    """
    rng = np.random.default_rng(seed)
    archetype_mix = archetype_mix or ARCHETYPE_MIX_DEFAULT
    archetypes = list(archetype_mix.keys())
    weights = np.array([archetype_mix[a] for a in archetypes])
    weights = weights / weights.sum()

    topo = FeederTopology(substation_node_id=substation_id)

    for t_idx in range(n_transformers):
        transformer_id = f"{substation_id}-T{t_idx+1:02d}"
        rating = _pick_rating_kva(connections_per_transformer, rng)
        cat = TRANSFORMER_CATALOG[rating]
        transformer = TransformerSpec(
            node_id=transformer_id,
            rating_kva=rating,
            no_load_loss_kw=cat["no_load_loss_kw"],
            load_loss_kw=cat["load_loss_kw"],
            impedance_pct=cat["impedance_pct"],
        )
        topo.transformers.append(transformer)
        topo.node_records.append(
            (
                substation_id,
                transformer_id,
                NodeType.TRANSFORMER,
                f"Transformer {t_idx+1}",
                {
                    "rating_kva": rating,
                    "no_load_loss_kw": cat["no_load_loss_kw"],
                    "load_loss_kw": cat["load_loss_kw"],
                    "impedance_pct": cat["impedance_pct"],
                    "vector_group": transformer.vector_group,
                    "mv_kv": MV_KV,
                    "lv_kv": LV_KV,
                },
            )
        )

        feeder_id = f"{transformer_id}-F1"
        topo.node_records.append(
            (
                transformer_id,
                feeder_id,
                NodeType.LV_FEEDER,
                f"LV Feeder {t_idx+1}.1",
                {
                    "conductor": "70mm2 AAAC ABC (representative)",
                    "r_ohm_per_km": LV_FEEDER_R_OHM_PER_KM,
                    "x_ohm_per_km": LV_FEEDER_X_OHM_PER_KM,
                },
            )
        )

        archetype_idx_choices = rng.choice(
            len(archetypes), size=connections_per_transformer, p=weights
        )
        # Round-robin phase assignment (balanced by design, imbalance then
        # emerges from real load differences, not from lopsided phase
        # allocation) -- fixed here, once, for the connection's lifetime.
        phase_order = rng.permutation(connections_per_transformer)
        phase_by_index = {int(pos): (i % 3) + 1 for i, pos in enumerate(phase_order)}

        for c_idx, idx in enumerate(archetype_idx_choices):
            archetype = archetypes[idx]
            connection_id = f"{feeder_id}-C{c_idx+1:03d}"
            distance_m = float(rng.uniform(20, 300))
            topo.connections.append(
                ConnectionSpec(
                    connection_id=connection_id,
                    transformer_node_id=transformer_id,
                    lv_feeder_node_id=feeder_id,
                    archetype=ConnectionArchetype(archetype),
                    distance_from_transformer_m=distance_m,
                    service_drop_r_ohm=SERVICE_DROP_R_OHM_PER_KM * distance_m / 1000,
                    service_drop_x_ohm=SERVICE_DROP_X_OHM_PER_KM * distance_m / 1000,
                    phase=phase_by_index[c_idx],
                )
            )

    return topo
