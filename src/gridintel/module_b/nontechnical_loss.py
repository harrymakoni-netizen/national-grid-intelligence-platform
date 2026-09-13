"""Section 7.2's energy-balance equation, at transformer level:

  Non-technical loss = Energy measured into the transformer
                        - Energy accounted to customers
                        - Modelled technical loss

No sensing hardware exists yet (item 6 is deferred to real firmware/bench
work), so "energy measured into the transformer" cannot come from a real
device. It is instead computed from the SAME synthetic ground truth the
generator itself produces -- sum of every truly-connected connection's
physical draw plus the true technical loss -- which is exactly what a
perfect transformer monitor would report. This is `measured_inflow_kw` and
is synthetic-only by construction: there is no equivalent function for a
real feeder in this codebase, because there is no real feeder yet.

"Truly connected" is read from the connection_id's own naming convention
(`<substation>-<transformer>-F<n>-C<m>`, fixed at generation time in
topology.py) rather than from the association table, because a real
sensor reads physical reality regardless of what the platform currently
believes a connection's transformer is -- that belief is exactly what
Section 11.1 says can be wrong, and ground truth in this codebase is never
allowed to depend on it.

The other two terms are NOT privileged:
  - `energy_accounted_kw`: Module A's reconstruction summed over every
    connection CURRENTLY associated with the transformer (not ground truth).
  - `modelled_technical_loss_kw`: the digital twin's estimate (Section 7),
    fed Module A's reconstruction as its consumption input (not ground
    truth) -- the actual production pipeline: vending events -> Module A
    -> digital twin -> this equation.

The residual conflates several distinct things by construction -- real
non-technical loss, Module A's reconstruction error, the twin's coverage
gap, and any connection missing from the association table entirely -- and
cannot be decomposed among them from this equation alone. It is a systems-
level sanity signal (does the residual track injected anomalies at all),
not a per-connection attribution -- that is what pipeline.py's case queue
is for.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import Connection, GroundTruthConsumption, GroundTruthTechnicalLoss
from gridintel.digitaltwin.twin import compute_modelled_loss
from gridintel.hierarchy.aggregate import resolve_connections
from gridintel.module_a.reconstruct import reconstruct_for_connection


def _measured_inflow_kw(session: Session, scenario_id: str, transformer_node_id: str) -> pd.Series:
    true_connection_ids = [
        c
        for c in session.execute(select(Connection.id)).scalars()
        if c.startswith(f"{transformer_node_id}-")
    ]
    rows = session.execute(
        select(GroundTruthConsumption.ts, GroundTruthConsumption.kw)
        .where(GroundTruthConsumption.scenario_id == scenario_id)
        .where(GroundTruthConsumption.connection_id.in_(true_connection_ids))
    ).all()
    consumption_sum = pd.DataFrame(rows, columns=["ts", "kw"]).groupby("ts")["kw"].sum()

    loss_rows = session.execute(
        select(GroundTruthTechnicalLoss.ts, GroundTruthTechnicalLoss.loss_kw)
        .where(GroundTruthTechnicalLoss.scenario_id == scenario_id)
        .where(GroundTruthTechnicalLoss.network_node_id == transformer_node_id)
    ).all()
    loss = pd.DataFrame(loss_rows, columns=["ts", "loss_kw"]).set_index("ts")["loss_kw"]

    combined = pd.concat([consumption_sum.rename("consumption"), loss.rename("loss")], axis=1, sort=True).fillna(0.0)
    result = combined["consumption"] + combined["loss"]
    result.index = pd.to_datetime(result.index)
    if result.index.tz is None:
        result.index = result.index.tz_localize("UTC")
    return result


def _reconstruct_all_connections(
    session: Session,
    scenario_id: str,
    transformer_node_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> pd.DataFrame:
    """Long DataFrame (connection_id, ts, kw) of Module A's reconstruction
    for every connection CURRENTLY associated with the transformer --
    computed once and shared by both the accounted-energy sum and the
    twin's per-connection input, rather than reconstructing twice.
    """
    resolved = [
        r for r in resolve_connections(session, transformer_node_id) if r.network_node_id == transformer_node_id
    ]
    frames = []
    for r in resolved:
        try:
            result = reconstruct_for_connection(
                session, r.connection_id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
            )
        except ValueError:
            continue
        frames.append(pd.DataFrame({"connection_id": r.connection_id, "ts": result.index, "kw": result.mean_kw}))
    if not frames:
        return pd.DataFrame(columns=["connection_id", "ts", "kw"])
    df = pd.concat(frames, ignore_index=True)
    df["kw"] = df["kw"].fillna(0.0)
    return df


@dataclass
class NonTechnicalLossResult:
    series: pd.Series  # non-technical loss residual, kW, indexed by ts
    measured_inflow_kw: pd.Series
    energy_accounted_kw: pd.Series
    modelled_technical_loss_kw: pd.Series
    twin_coverage_fraction: float


def compute_nontechnical_loss(
    session: Session,
    scenario_id: str,
    transformer_node_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> NonTechnicalLossResult:
    measured_inflow = _measured_inflow_kw(session, scenario_id, transformer_node_id)

    per_connection_df = _reconstruct_all_connections(
        session, scenario_id, transformer_node_id, start=start, end=end, interval_minutes=interval_minutes
    )
    energy_accounted = (
        per_connection_df.groupby("ts")["kw"].sum() if not per_connection_df.empty else pd.Series(dtype=float)
    )

    twin_result = compute_modelled_loss(session, transformer_node_id, per_connection_df)
    modelled_loss = twin_result.loss_series.set_index("ts")["total_loss_kw"]
    if modelled_loss.index.tz is None:
        modelled_loss.index = pd.to_datetime(modelled_loss.index).tz_localize("UTC")

    combined = pd.concat(
        [
            measured_inflow.rename("measured"),
            energy_accounted.rename("accounted"),
            modelled_loss.rename("modelled_loss"),
        ],
        axis=1,
        sort=True,
    ).dropna()
    residual = combined["measured"] - combined["accounted"] - combined["modelled_loss"]

    return NonTechnicalLossResult(
        series=residual,
        measured_inflow_kw=combined["measured"],
        energy_accounted_kw=combined["accounted"],
        modelled_technical_loss_kw=combined["modelled_loss"],
        twin_coverage_fraction=twin_result.coverage_fraction,
    )
