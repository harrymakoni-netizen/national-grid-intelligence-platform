"""Subtree-level consumption aggregation for the drill-down interface,
built from Module A's reconstruction -- NOT privileged ground truth. This
is what the platform would actually show in production, where ground
truth consumption does not exist. (gridsynth ground truth is used
elsewhere, always explicitly for synthetic validation, never for display.)
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from gridintel.hierarchy.aggregate import resolve_connections
from gridintel.module_a.reconstruct import reconstruct_for_connection


def reconstructed_consumption_for_subtree(
    session: Session,
    root_id: str,
    scenario_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> pd.DataFrame:
    """Long DataFrame (connection_id, ts, kw) of Module A's reconstruction
    for every connection currently resolved beneath root_id, at any depth.
    """
    resolved = resolve_connections(session, root_id)
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
