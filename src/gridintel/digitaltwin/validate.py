"""Section 15's acceptance criterion for the digital twin, made executable:

  "Computed technical loss on the synthetic feeder matches the loss
  imposed by the generator within a stated tolerance across a range of
  loading conditions."

This can only be checked meaningfully on synthetic data (a scenario_id is
required), because it needs GroundTruthTechnicalLoss to compare against --
exactly the privileged, full-information figure that does not exist for a
real feeder. See digitaltwin/twin.py's module docstring for why the twin
itself never has access to it.

The comparison is reported alongside `coverage_fraction`: under full
association coverage the twin should match ground truth almost exactly
(same physics engine, same inputs); under partial coverage -- the realistic
case -- it is EXPECTED to understate loss, and the size of that
understatement is itself a useful, reportable number, not a defect to
explain away.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import GroundTruthConsumption, GroundTruthTechnicalLoss
from gridintel.digitaltwin.twin import TwinResult, compute_modelled_loss


@dataclass
class TwinComparison:
    transformer_node_id: str
    coverage_fraction: float
    n_associated_connections: int
    n_placeable_connections: int
    mean_ground_truth_loss_kw: float
    mean_modelled_loss_kw: float
    mean_relative_error: float
    n_intervals_compared: int


def _physical_consumption(session: Session, scenario_id: str) -> pd.DataFrame:
    rows = session.execute(
        select(
            GroundTruthConsumption.connection_id,
            GroundTruthConsumption.ts,
            GroundTruthConsumption.kw,
        ).where(GroundTruthConsumption.scenario_id == scenario_id)
    ).all()
    df = pd.DataFrame(rows, columns=["connection_id", "ts", "kw"])
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def compare_twin_to_ground_truth(
    session: Session, scenario_id: str, transformer_node_id: str
) -> TwinComparison:
    physical = _physical_consumption(session, scenario_id)
    result: TwinResult = compute_modelled_loss(session, transformer_node_id, physical)

    gt_rows = session.execute(
        select(GroundTruthTechnicalLoss.ts, GroundTruthTechnicalLoss.loss_kw)
        .where(GroundTruthTechnicalLoss.scenario_id == scenario_id)
        .where(GroundTruthTechnicalLoss.network_node_id == transformer_node_id)
    ).all()
    gt = pd.DataFrame(gt_rows, columns=["ts", "loss_kw"])
    gt["ts"] = pd.to_datetime(gt["ts"])

    compared = pd.concat(
        [gt.set_index("ts")["loss_kw"].rename("gt"), result.loss_series.set_index("ts")["total_loss_kw"].rename("twin")],
        axis=1,
    ).dropna()

    relative_error = ((compared["twin"] - compared["gt"]).abs() / compared["gt"]).mean() if len(compared) else float("nan")

    return TwinComparison(
        transformer_node_id=transformer_node_id,
        coverage_fraction=result.coverage_fraction,
        n_associated_connections=result.n_associated_connections,
        n_placeable_connections=result.n_placeable_connections,
        mean_ground_truth_loss_kw=float(compared["gt"].mean()) if len(compared) else float("nan"),
        mean_modelled_loss_kw=float(compared["twin"].mean()) if len(compared) else float("nan"),
        mean_relative_error=float(relative_error),
        n_intervals_compared=len(compared),
    )
