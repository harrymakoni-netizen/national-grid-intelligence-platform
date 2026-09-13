"""Physically-computed technical loss, per transformer per interval --
never an imposed percentage (Section 12.1's explicit requirement).

Loss has two physically distinct components, computed by two different
methods deliberately:

1. Transformer core + copper loss. This does NOT need a power-flow solver
   -- it is a standard closed-form relationship from nameplate data:
   no-load loss is roughly constant, load loss scales with (load/rated)^2.
   Collapsing these into a single "loss percentage" (as a naive generator
   might) would erase exactly the loading-dependence that makes computed
   loss an informative feature downstream -- see topology.py's per-rating
   catalog for the no_load/load loss split this uses.

2. LV network conductor loss. This DOES need a power-flow solver, because
   ZETDC's low-voltage network is single-phase-tapped off a three-phase LV
   main and therefore genuinely unbalanced -- exactly the case a balanced
   positive-sequence tool like pandapower cannot represent. OpenDSS is used
   here for that reason (see the design note in topology.py and the
   project's build-plan discussion of Section 7). Each connection is
   assigned to one of three LV phases; the resulting loss is whatever the
   solver computes for that specific unbalanced loading, not an assumption.

The OpenDSS circuit per transformer models only the LV side (from the
transformer's secondary busbar, treated as an ideal stiff 400V source, out
to each connection's service drop). Transformer losses are added
separately per (1) above -- solving the transformer's own impedance in
OpenDSS as well would be double-counting against the analytical figure.
"""
from __future__ import annotations

import numpy as np
import opendssdirect as dss
import pandas as pd

from gridintel.gridsynth.topology import ConnectionSpec, FeederTopology, TransformerSpec

LV_PHASE_KV = 0.230  # single-phase line-to-neutral voltage on a 400V LV system


def _assign_phases(connection_ids: list[str], seed: int) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    order = list(connection_ids)
    rng.shuffle(order)
    return {cid: (i % 3) + 1 for i, cid in enumerate(order)}


def _build_transformer_lv_circuit(
    transformer: TransformerSpec,
    connections: list[ConnectionSpec],
    phase_by_connection: dict[str, int],
) -> None:
    dss.Text.Command("clear")
    dss.Text.Command("set defaultbasefrequency=50")
    dss.Text.Command(
        f"new circuit.{transformer.node_id} basekv={LV_PHASE_KV * (3 ** 0.5):.4f} "
        f"pu=1.0 phases=3 bus1=lv_bus"
    )
    for conn in connections:
        phase = phase_by_connection[conn.connection_id]
        bus_name = conn.connection_id.replace("-", "_")
        length_km = max(conn.distance_from_transformer_m, 1.0) / 1000.0
        dss.Text.Command(
            f"new line.svc_{bus_name} phases=1 bus1=lv_bus.{phase} bus2={bus_name}.{phase} "
            f"r1={conn.service_drop_r_ohm / length_km:.6f} "
            f"x1={conn.service_drop_x_ohm / length_km:.6f} "
            f"length={length_km:.6f} units=km"
        )
        dss.Text.Command(
            f"new load.{bus_name} bus1={bus_name}.{phase} phases=1 kV={LV_PHASE_KV} "
            f"kW=0.01 pf=0.98 model=1"
        )
    dss.Text.Command("set voltagebases=[0.4]")
    dss.Text.Command("calcvoltagebases")


def transformer_loss_kw(rating_kva: float, load_kw: float, no_load_loss_kw: float, load_loss_kw: float) -> float:
    """Closed-form transformer loss: core loss (~constant) + copper loss
    scaling with the square of loading fraction."""
    loading_fraction = min(abs(load_kw) / rating_kva, 2.0) if rating_kva > 0 else 0.0
    return no_load_loss_kw + load_loss_kw * loading_fraction**2


def compute_technical_losses(
    topology: FeederTopology,
    consumption: pd.DataFrame,
    *,
    seed: int,
) -> pd.DataFrame:
    """consumption: long DataFrame with connection_id, ts, kw (physical).
    Returns long DataFrame: network_node_id (transformer), ts, loss_kw
    (LV network loss + transformer core/copper loss, summed).
    """
    conn_by_transformer: dict[str, list[ConnectionSpec]] = {}
    for conn in topology.connections:
        conn_by_transformer.setdefault(conn.transformer_node_id, []).append(conn)

    pivot = consumption.pivot(index="ts", columns="connection_id", values="kw")
    timestamps = pivot.index

    records = []
    for transformer in topology.transformers:
        conns = conn_by_transformer.get(transformer.node_id, [])
        if not conns:
            continue
        conn_ids = [c.connection_id for c in conns]
        phase_by_connection = _assign_phases(conn_ids, seed)
        _build_transformer_lv_circuit(transformer, conns, phase_by_connection)

        loads_kw = pivot[conn_ids]

        for ts, row in zip(timestamps, loads_kw.itertuples(index=False)):
            total_load_kw = 0.0
            for conn_id, kw in zip(conn_ids, row):
                bus_name = conn_id.replace("-", "_")
                kw = max(float(kw), 0.001)
                dss.Loads.Name(bus_name)
                dss.Loads.kW(kw)
                total_load_kw += kw

            dss.Solution.Solve()
            network_losses_w = dss.Circuit.Losses()[0]
            network_loss_kw = network_losses_w / 1000.0

            xfmr_loss_kw = transformer_loss_kw(
                transformer.rating_kva,
                total_load_kw,
                transformer.no_load_loss_kw,
                transformer.load_loss_kw,
            )

            records.append(
                {
                    "network_node_id": transformer.node_id,
                    "ts": ts,
                    "loss_kw": network_loss_kw + xfmr_loss_kw,
                }
            )

    return pd.DataFrame.from_records(records)
