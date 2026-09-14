"""Per-transformer asset health, ranked (Section 8.3's operational output:
"a hazard function per asset from which remaining useful life and failure
probability over a chosen horizon are derived").

What is produced here is the thermal-ageing prior only -- a physically
computed rate of insulation consumption and the remaining life implied if
the observed loading pattern continues. It is NOT a hazard function fitted
to observed failures, because no transformer in this system has failed and
no sensing hardware exists to have watched one fail. Section 8.3's
evaluation criterion (concordance against observed events) therefore
cannot be reported, and is not.

The ranking is still operationally useful in exactly the way Section 8.3
describes -- it reallocates a maintenance budget rationally -- provided
nobody reads "remaining life" as a prediction of when a specific unit will
fail. It is a statement about insulation thermal ageing under the loading
this platform has reconstructed, nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import NetworkNode, NodeType
from gridintel.digitaltwin.twin import compute_modelled_loss
from gridintel.hierarchy.aggregate import descendant_ids, resolve_connections
from gridintel.module_a.reconstruct import reconstruct_for_connection
from gridintel.module_c.thermal import ThermalResult, compute_thermal_ageing


@dataclass
class TransformerHealth:
    transformer_id: str
    name: str
    rating_kva: float
    peak_load_factor: float
    mean_load_factor: float
    peak_hot_spot_c: float
    mean_ageing_rate: float
    hours_above_reference: float
    hours_above_cyclic_limit: float
    projected_life_years: float | None   # None when not thermally limited
    thermally_limited: bool
    risk_band: str
    observed_days: float
    thermal: ThermalResult | None = None


def _transformer_loading(
    session: Session,
    scenario_id: str,
    transformer_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> pd.Series:
    """Total load seen by the transformer, from the connections currently
    associated with it. Uses Module A's reconstruction -- the same input
    the digital twin runs on -- so the thermal model inherits, and must
    disclose, that estimate's error.
    """
    resolved = [
        r for r in resolve_connections(session, transformer_id) if r.network_node_id == transformer_id
    ]
    frames = []
    for r in resolved:
        try:
            result = reconstruct_for_connection(
                session, r.connection_id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
            )
        except ValueError:
            continue
        frames.append(pd.Series(result.mean_kw, index=result.index).fillna(0.0))
    if not frames:
        return pd.Series(dtype=float)
    return pd.concat(frames, axis=1).sum(axis=1)


def assess_transformer(
    session: Session,
    scenario_id: str,
    transformer_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
    include_series: bool = False,
) -> TransformerHealth | None:
    node = session.get(NetworkNode, transformer_id)
    if node is None or node.node_type != NodeType.TRANSFORMER.value:
        return None

    load = _transformer_loading(
        session, scenario_id, transformer_id, start=start, end=end, interval_minutes=interval_minutes
    )
    if len(load) < 2:
        return None

    attrs = node.attributes
    thermal = compute_thermal_ageing(
        pd.DatetimeIndex(load.index),
        load.to_numpy(),
        rating_kva=attrs["rating_kva"],
        no_load_loss_kw=attrs["no_load_loss_kw"],
        load_loss_kw=attrs["load_loss_kw"],
    )

    return TransformerHealth(
        transformer_id=transformer_id,
        name=node.name,
        rating_kva=attrs["rating_kva"],
        peak_load_factor=float(thermal.load_factor.max()),
        mean_load_factor=float(thermal.load_factor.mean()),
        peak_hot_spot_c=thermal.peak_hot_spot_c,
        mean_ageing_rate=thermal.mean_ageing_rate,
        hours_above_reference=thermal.hours_above_reference,
        hours_above_cyclic_limit=thermal.hours_above_cyclic_limit,
        projected_life_years=thermal.projected_life_years,
        thermally_limited=thermal.thermally_limited,
        risk_band=thermal.risk_band,
        observed_days=thermal.observed_hours / 24.0,
        thermal=thermal if include_series else None,
    )


def rank_transformers(
    session: Session,
    scenario_id: str,
    root_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> list[TransformerHealth]:
    """Every transformer beneath root_id, worst thermal ageing first --
    the maintenance prioritisation Section 8.3 exists to produce."""
    results = []
    for node_id in descendant_ids(session, root_id):
        node = session.get(NetworkNode, node_id)
        if node is None or node.node_type != NodeType.TRANSFORMER.value:
            continue
        health = assess_transformer(
            session, scenario_id, node_id, start=start, end=end, interval_minutes=interval_minutes
        )
        if health is not None:
            results.append(health)
    results.sort(key=lambda h: h.mean_ageing_rate, reverse=True)
    return results
