"""DB-facing orchestration: resolves the connections under a transformer,
runs Module A reconstruction for each, computes Section 8.2 features, and
produces the ranked case queue -- "predicted cause, confidence score, an
estimated recoverable energy quantity, and the evidence supporting the
classification" -- Section 8.2's specified output shape.

Ranking is by weak-supervision confidence (primary) and unsupervised
suspicion score (secondary tiebreaker): only connections a labelling
function actually fired on are queued at all, consistent with "precision
at the top of the ranked list" being the metric that matters (Section
8.2) -- a long tail of low-confidence unsupervised-only suspicion would
hurt exactly that metric without Section 8.2's own field-loop precedent
for using it directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import Connection, VendingEvent
from gridintel.gridsynth.load_shapes import irradiance_for_period
from gridintel.hierarchy.aggregate import resolve_connections
from gridintel.module_a.reconstruct import reconstruct_for_connection
from gridintel.module_b.features import ConnectionFeatures, assign_peer_group_z_scores, compute_connection_features
from gridintel.module_b.unsupervised import compute_suspicion_scores
from gridintel.module_b.weak_supervision import NORMAL, WeakLabel, classify


@dataclass
class CaseQueueEntry:
    connection_id: str
    predicted_cause: str
    confidence: float
    suspicion_score: float
    estimated_recoverable_kw: float
    evidence: dict = field(default_factory=dict)


def _purchase_timestamps(session: Session, connection_id: str, scenario_id: str) -> pd.DatetimeIndex:
    rows = session.execute(
        select(VendingEvent.ts)
        .where(VendingEvent.connection_id == connection_id)
        .where(VendingEvent.scenario_id == scenario_id)
    ).all()
    if not rows:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex([r[0] for r in rows]).tz_localize("UTC")


def compute_features_for_transformer(
    session: Session,
    transformer_node_id: str,
    scenario_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> list[ConnectionFeatures]:
    resolved = [
        r
        for r in resolve_connections(session, transformer_node_id)
        if r.network_node_id == transformer_node_id
    ]
    irradiance = irradiance_for_period(start, end, interval_minutes)

    all_features: list[ConnectionFeatures] = []
    for r in resolved:
        connection = session.get(Connection, r.connection_id)
        try:
            result = reconstruct_for_connection(
                session, r.connection_id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
            )
        except ValueError:
            continue  # no purchase history for this connection in the window -- nothing to featurize

        recon = pd.Series(result.mean_kw, index=result.index)
        purchase_ts = _purchase_timestamps(session, r.connection_id, scenario_id)

        features = compute_connection_features(
            r.connection_id,
            recon,
            purchase_ts,
            connection_status=connection.status,
            irradiance_w_m2=irradiance,
        )
        all_features.append(features)

    assign_peer_group_z_scores(all_features)
    return all_features


def build_case_queue(
    session: Session,
    transformer_node_id: str,
    scenario_id: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
    seed: int = 0,
) -> list[CaseQueueEntry]:
    features = compute_features_for_transformer(
        session, transformer_node_id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
    )
    if not features:
        return []

    suspicion = compute_suspicion_scores(features, seed=seed)
    labels: dict[str, WeakLabel] = {f.connection_id: classify(f) for f in features}
    features_by_id = {f.connection_id: f for f in features}

    entries = []
    for connection_id, label in labels.items():
        if label.predicted_cause == NORMAL:
            continue
        f = features_by_id[connection_id]
        entries.append(
            CaseQueueEntry(
                connection_id=connection_id,
                predicted_cause=label.predicted_cause,
                confidence=label.confidence,
                suspicion_score=suspicion[connection_id],
                estimated_recoverable_kw=f.estimated_recoverable_kw,
                evidence={
                    "fractional_change": f.fractional_change,
                    "daylight_fractional_change": f.daylight_fractional_change,
                    "evening_fractional_change": f.evening_fractional_change,
                    "irradiance_correlation": f.irradiance_correlation,
                    "step_sharpness": f.step_sharpness,
                    "zero_purchase_activity_recent": f.zero_purchase_activity_recent,
                    "connection_inactive": f.connection_inactive,
                    "peer_group_z_score": f.peer_group_z_score,
                    "open_segment_ratio": f.open_segment_ratio,
                    "votes": label.votes,
                },
            )
        )

    entries.sort(key=lambda e: (e.confidence, e.suspicion_score), reverse=True)
    return entries
