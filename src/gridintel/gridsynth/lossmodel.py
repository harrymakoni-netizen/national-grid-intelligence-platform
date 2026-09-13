"""Ground-truth technical loss for a synthetic scenario: physically
computed from the generator's TRUE topology and TRUE physical consumption,
using every connection that actually exists on the feeder regardless of
what the platform's association records currently claim.

This is deliberately the privileged, full-information counterpart to
digitaltwin.twin's operational computation, which only sees what the
platform currently knows. Both call the same physics
(digitaltwin.opendss_engine) so any gap between the two is attributable to
missing knowledge, not to a difference in the two implementations -- see
opendss_engine.py's module docstring.
"""
from __future__ import annotations

import pandas as pd

from gridintel.digitaltwin.opendss_engine import CircuitConnection, solve_loss_series
from gridintel.gridsynth.topology import ConnectionSpec, FeederTopology
from gridintel.network_catalog import SERVICE_DROP_R_OHM_PER_KM, SERVICE_DROP_X_OHM_PER_KM


def transformer_loss_kw(rating_kva: float, load_kw: float, no_load_loss_kw: float, load_loss_kw: float) -> float:
    from gridintel.digitaltwin.opendss_engine import transformer_loss_kw as _impl

    return _impl(rating_kva, load_kw, no_load_loss_kw, load_loss_kw)


def compute_technical_losses(
    topology: FeederTopology,
    consumption: pd.DataFrame,
    *,
    seed: int,
) -> pd.DataFrame:
    """consumption: long DataFrame with connection_id, ts, kw (physical,
    the true draw regardless of metering/billing status). Returns long
    DataFrame: network_node_id (transformer), ts, loss_kw (LV network loss
    + transformer core/copper loss, summed) -- the full-knowledge ground
    truth every twin result is ultimately compared against.
    """
    conn_by_transformer: dict[str, list[ConnectionSpec]] = {}
    for conn in topology.connections:
        conn_by_transformer.setdefault(conn.transformer_node_id, []).append(conn)

    pivot = consumption.pivot(index="ts", columns="connection_id", values="kw")

    records = []
    for transformer in topology.transformers:
        conns = conn_by_transformer.get(transformer.node_id, [])
        if not conns:
            continue

        circuit_conns = [
            CircuitConnection(connection_id=c.connection_id, distance_m=c.distance_from_transformer_m, phase=c.phase)
            for c in conns
        ]
        conn_ids = [c.connection_id for c in conns]
        consumption_by_ts = {
            ts: {cid: float(kw) for cid, kw in zip(conn_ids, row)}
            for ts, row in zip(pivot.index, pivot[conn_ids].itertuples(index=False))
        }

        loss_df = solve_loss_series(
            transformer.node_id,
            circuit_conns,
            r_ohm_per_km=SERVICE_DROP_R_OHM_PER_KM,
            x_ohm_per_km=SERVICE_DROP_X_OHM_PER_KM,
            rating_kva=transformer.rating_kva,
            no_load_loss_kw=transformer.no_load_loss_kw,
            load_loss_kw=transformer.load_loss_kw,
            consumption_by_ts=consumption_by_ts,
        )
        for row in loss_df.itertuples(index=False):
            records.append(
                {"network_node_id": transformer.node_id, "ts": row.ts, "loss_kw": row.total_loss_kw}
            )

    return pd.DataFrame.from_records(records)
