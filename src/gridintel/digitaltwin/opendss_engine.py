"""The single OpenDSS-based physics engine used by both:

- gridsynth.lossmodel, which computes GROUND TRUTH technical loss for a
  synthetic scenario from the generator's true topology and true physical
  consumption (every connection, regardless of what the platform currently
  believes about it), and
- digitaltwin.twin, the operational model (Section 7), which computes
  MODELLED technical loss from whatever the platform actually knows --
  only connections with a confirmed transformer association AND a known
  electrical placement, fed whatever consumption estimate is available.

Sharing one engine matters: if ground truth and the twin used separately
written circuit-building code, a numerical mismatch between them could
mean either "the network truly has unmodelled loss" or "the two
implementations disagree" -- and nobody could tell which. Using the same
engine collapses that ambiguity: any gap between GroundTruthTechnicalLoss
and ModelledTechnicalLoss for the same scenario/node/interval is
attributable to what data each was given (full topology vs. partial
knowledge), never to an implementation difference.

Loss has two physically distinct components, computed by two different
methods deliberately:

1. Transformer core + copper loss -- closed-form from nameplate data
   (no-load loss ~constant, load loss ~(load/rated)^2), not a power-flow
   output. Collapsing this into a single "loss percentage" would erase the
   loading-dependence that makes computed loss an informative feature.
2. LV network conductor loss -- genuinely needs a power-flow solver,
   because ZETDC's LV network is single-phase-tapped off a three-phase
   main and therefore unbalanced, which a balanced positive-sequence tool
   (pandapower) cannot represent. OpenDSS is used for exactly this reason.
"""
from __future__ import annotations

from dataclasses import dataclass

import opendssdirect as dss
import pandas as pd

LV_PHASE_KV = 0.230  # single-phase line-to-neutral voltage on a 400V LV system


@dataclass(frozen=True)
class CircuitConnection:
    connection_id: str
    distance_m: float
    phase: int  # 1, 2, or 3


def build_lv_circuit(
    transformer_id: str,
    connections: list[CircuitConnection],
    *,
    r_ohm_per_km: float,
    x_ohm_per_km: float,
) -> None:
    """Builds a star of single-phase service-drop laterals from the
    transformer's LV busbar (treated as an ideal stiff 400V three-phase
    source -- the transformer's own impedance/losses are added separately
    via transformer_loss_kw, not solved here, to avoid double-counting).
    """
    dss.Text.Command("clear")
    dss.Text.Command("set defaultbasefrequency=50")
    dss.Text.Command(
        f"new circuit.{transformer_id} basekv={LV_PHASE_KV * (3 ** 0.5):.4f} "
        f"pu=1.0 phases=3 bus1=lv_bus"
    )
    for conn in connections:
        bus_name = conn.connection_id.replace("-", "_")
        length_km = max(conn.distance_m, 1.0) / 1000.0
        dss.Text.Command(
            f"new line.svc_{bus_name} phases=1 bus1=lv_bus.{conn.phase} bus2={bus_name}.{conn.phase} "
            f"r1={r_ohm_per_km:.6f} x1={x_ohm_per_km:.6f} length={length_km:.6f} units=km"
        )
        dss.Text.Command(
            f"new load.{bus_name} bus1={bus_name}.{conn.phase} phases=1 kV={LV_PHASE_KV} "
            f"kW=0.01 pf=0.98 model=1"
        )
    dss.Text.Command("set voltagebases=[0.4]")
    dss.Text.Command("calcvoltagebases")


def solve_network_loss_kw(connections: list[CircuitConnection], loads_kw: dict[str, float]) -> float:
    """Sets each connection's load for the circuit already built by
    build_lv_circuit, solves, and returns the LV network's own loss (kW) --
    NOT including transformer core/copper loss, which is computed
    separately by transformer_loss_kw.
    """
    for conn in connections:
        bus_name = conn.connection_id.replace("-", "_")
        kw = max(float(loads_kw.get(conn.connection_id, 0.0)), 0.001)
        dss.Loads.Name(bus_name)
        dss.Loads.kW(kw)
    dss.Solution.Solve()
    return dss.Circuit.Losses()[0] / 1000.0


def transformer_loss_kw(
    rating_kva: float, load_kw: float, no_load_loss_kw: float, load_loss_kw: float
) -> float:
    """Closed-form transformer loss: core loss (~constant) + copper loss
    scaling with the square of loading fraction."""
    loading_fraction = min(abs(load_kw) / rating_kva, 2.0) if rating_kva > 0 else 0.0
    return no_load_loss_kw + load_loss_kw * loading_fraction**2


def solve_loss_series(
    transformer_id: str,
    connections: list[CircuitConnection],
    *,
    r_ohm_per_km: float,
    x_ohm_per_km: float,
    rating_kva: float,
    no_load_loss_kw: float,
    load_loss_kw: float,
    consumption_by_ts: dict[pd.Timestamp, dict[str, float]],
) -> pd.DataFrame:
    """Builds the circuit once, solves it once per timestamp in
    consumption_by_ts, and returns a long DataFrame of
    (ts, network_loss_kw, transformer_loss_kw, total_loss_kw).
    """
    if not connections:
        return pd.DataFrame(columns=["ts", "network_loss_kw", "transformer_loss_kw", "total_loss_kw"])

    build_lv_circuit(transformer_id, connections, r_ohm_per_km=r_ohm_per_km, x_ohm_per_km=x_ohm_per_km)

    records = []
    for ts, loads_kw in consumption_by_ts.items():
        network_loss = solve_network_loss_kw(connections, loads_kw)
        total_load_kw = sum(max(loads_kw.get(c.connection_id, 0.0), 0.0) for c in connections)
        xfmr_loss = transformer_loss_kw(rating_kva, total_load_kw, no_load_loss_kw, load_loss_kw)
        records.append(
            {
                "ts": ts,
                "network_loss_kw": network_loss,
                "transformer_loss_kw": xfmr_loss,
                "total_loss_kw": network_loss + xfmr_loss,
            }
        )
    return pd.DataFrame.from_records(records)
