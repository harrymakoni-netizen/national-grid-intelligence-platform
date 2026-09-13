"""Module A's public entry point: turn a connection's purchase history into
an estimated consumption profile with uncertainty (Section 8.1).

reconstruct_from_events() is a pure function over vending events + an
archetype label + (optionally) shedding windows -- no database dependency,
so it can run identically against synthetic scenario data, a real
connection's vending history, or the held-out real interval dataset with
simulated purchases (validate.py uses all three). reconstruct_for_connection()
is the thin DB-facing adapter used for synthetic validation in this milestone.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import Connection, ConnectionArchetype, NetworkNode, VendingEvent
from gridintel.module_a.prior import population_shape_prior
from gridintel.module_a.segment_reconstruction import ReconstructionResult, run_segment_reconstruction
from gridintel.shedding_schedule import SheddingWindow


def _bin_purchases_to_interval(
    index: pd.DatetimeIndex, purchase_ts: pd.Series, purchase_kwh: pd.Series, interval_minutes: int
) -> np.ndarray:
    out = np.zeros(len(index))
    if len(purchase_ts) == 0:
        return out
    purchase_ts = pd.DatetimeIndex(purchase_ts)
    # Database round-trips frequently lose tz-awareness (SQLite has no
    # native timezone type); align to the target index's tz rather than
    # letting a naive/aware mismatch raise.
    if index.tz is not None and purchase_ts.tz is None:
        purchase_ts = purchase_ts.tz_localize(index.tz)
    elif index.tz is None and purchase_ts.tz is not None:
        purchase_ts = purchase_ts.tz_localize(None)
    positions = index.get_indexer(purchase_ts, method="ffill")
    # get_indexer with ffill maps each purchase to the interval it falls
    # within (the most recent grid point at or before the purchase time).
    for pos, kwh in zip(positions, purchase_kwh):
        if pos >= 0:
            out[pos] += kwh
    return out


def reconstruct_from_events(
    vending_events: pd.DataFrame,  # columns: ts, kwh_purchased
    archetype: ConnectionArchetype,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
    shedding_windows: list[SheddingWindow] | None = None,
) -> ReconstructionResult:
    index = pd.date_range(start, end, freq=f"{interval_minutes}min", inclusive="left")
    prior_weight = population_shape_prior(archetype, index, shedding_windows=shedding_windows)

    events = vending_events.sort_values("ts")
    purchase_kwh_by_interval = _bin_purchases_to_interval(
        index, events["ts"], events["kwh_purchased"], interval_minutes
    )

    return run_segment_reconstruction(index, prior_weight, interval_minutes, purchase_kwh_by_interval)


def _shedding_windows_for_transformer(session: Session, transformer_node_id: str, scenario_config: dict) -> list[SheddingWindow] | None:
    node = session.get(NetworkNode, transformer_node_id)
    if node is None:
        return None
    group = node.attributes.get("shedding_group")
    schedule_json = scenario_config.get("shedding_schedule_by_group")
    if group is None or not schedule_json:
        return None
    windows = schedule_json.get(str(group))
    if not windows:
        return None
    return [SheddingWindow(dow=w["dow"], start_hour=w["start_hour"], end_hour=w["end_hour"]) for w in windows]


def reconstruct_for_connection(
    session: Session,
    connection_id: str,
    scenario_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> ReconstructionResult:
    """Synthetic-validation adapter: fetches this connection's archetype,
    its vending events for the given scenario, and (via its CURRENT
    transformer association, not any privileged ground truth) the shedding
    schedule applicable to it -- everything a production caller would also
    have, sourced from the database rather than generator internals.
    """
    from gridintel.db.models import SyntheticScenario

    connection = session.get(Connection, connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id!r} does not exist")
    archetype = ConnectionArchetype(connection.archetype)

    rows = session.execute(
        select(VendingEvent.ts, VendingEvent.kwh_purchased)
        .where(VendingEvent.connection_id == connection_id)
        .where(VendingEvent.scenario_id == scenario_id)
    ).all()
    events = pd.DataFrame(rows, columns=["ts", "kwh_purchased"])
    events["ts"] = pd.to_datetime(events["ts"])

    scenario = session.get(SyntheticScenario, scenario_id)
    shedding_windows = None

    # Resolve the connection's CURRENT transformer association directly.
    from gridintel.db.models import ConnectionAssociation

    assoc = session.execute(
        select(ConnectionAssociation.network_node_id)
        .where(ConnectionAssociation.connection_id == connection_id)
        .where(ConnectionAssociation.effective_to.is_(None))
    ).scalar_one_or_none()
    if assoc is not None and scenario is not None:
        shedding_windows = _shedding_windows_for_transformer(session, assoc, scenario.config)

    return reconstruct_from_events(
        events,
        archetype,
        start=start,
        end=end,
        interval_minutes=interval_minutes,
        shedding_windows=shedding_windows,
    )
