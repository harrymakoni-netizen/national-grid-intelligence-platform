"""The operational feeder digital twin (Section 7): computes modelled
technical loss for a transformer from whatever the platform currently
knows -- network records in the database, plus a caller-supplied
consumption estimate (ground truth for validation now; Module A's
reconstruction once it exists) -- never from privileged synthetic ground
truth.

This is deliberately NOT the same code path as
gridsynth.lossmodel.compute_technical_losses, which computes the full-
information ground truth a synthetic scenario is graded against. The twin
here only sees connections that are BOTH currently associated with this
transformer AND have a known electrical placement (distance + phase) --
exactly the state a real deployment would be in, per Section 11.1. Both
call the same underlying physics (digitaltwin.opendss_engine), so a gap
between the two is informative (incomplete knowledge), never an
implementation artefact.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy.orm import Session

from gridintel.db.models import NetworkNode, NodeType
from gridintel.digitaltwin.opendss_engine import CircuitConnection, solve_loss_series
from gridintel.hierarchy.aggregate import HierarchyError, resolve_connections
from gridintel.network_catalog import SERVICE_DROP_R_OHM_PER_KM, SERVICE_DROP_X_OHM_PER_KM


@dataclass
class TwinResult:
    transformer_node_id: str
    loss_series: pd.DataFrame  # columns: ts, network_loss_kw, transformer_loss_kw, total_loss_kw
    n_associated_connections: int
    n_placeable_connections: int

    @property
    def coverage_fraction(self) -> float:
        if self.n_associated_connections == 0:
            return 0.0
        return self.n_placeable_connections / self.n_associated_connections


def compute_modelled_loss(
    session: Session,
    transformer_node_id: str,
    consumption: pd.DataFrame,
    *,
    min_confidence: float = 0.0,
) -> TwinResult:
    """consumption: long DataFrame with columns connection_id, ts, kw --
    the caller's chosen consumption estimate for however many of the
    twin's placeable connections it has data for. Connections the twin can
    place but that have no row in `consumption` at a given timestamp are
    treated as zero load for that timestamp (a real production caller
    would fill this from Module A's reconstruction, which is specified to
    produce an estimate for every connection).
    """
    transformer = session.get(NetworkNode, transformer_node_id)
    if transformer is None:
        raise HierarchyError(f"network node {transformer_node_id!r} does not exist")
    if transformer.node_type != NodeType.TRANSFORMER.value:
        raise HierarchyError(
            f"{transformer_node_id!r} is a {transformer.node_type}, not a transformer"
        )

    resolved = [
        r
        for r in resolve_connections(session, transformer_node_id, min_confidence=min_confidence)
        if r.network_node_id == transformer_node_id
    ]
    placeable = [r for r in resolved if r.distance_from_transformer_m is not None and r.phase is not None]

    circuit_conns = [
        CircuitConnection(connection_id=r.connection_id, distance_m=r.distance_from_transformer_m, phase=r.phase)
        for r in placeable
    ]

    if circuit_conns:
        conn_ids = [c.connection_id for c in circuit_conns]
        pivot = (
            consumption[consumption["connection_id"].isin(conn_ids)]
            .pivot(index="ts", columns="connection_id", values="kw")
            .reindex(columns=conn_ids, fill_value=0.0)
        )
        consumption_by_ts = {
            ts: {cid: float(kw) for cid, kw in zip(conn_ids, row)}
            for ts, row in zip(pivot.index, pivot.itertuples(index=False))
        }
    else:
        consumption_by_ts = {}

    attrs = transformer.attributes
    loss_df = solve_loss_series(
        transformer_node_id,
        circuit_conns,
        r_ohm_per_km=SERVICE_DROP_R_OHM_PER_KM,
        x_ohm_per_km=SERVICE_DROP_X_OHM_PER_KM,
        rating_kva=attrs["rating_kva"],
        no_load_loss_kw=attrs["no_load_loss_kw"],
        load_loss_kw=attrs["load_loss_kw"],
        consumption_by_ts=consumption_by_ts,
    )

    return TwinResult(
        transformer_node_id=transformer_node_id,
        loss_series=loss_df,
        n_associated_connections=len(resolved),
        n_placeable_connections=len(placeable),
    )
