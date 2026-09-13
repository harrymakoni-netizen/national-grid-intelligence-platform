"""Unsupervised stage (Section 8.2): "Autoencoder reconstruction error and
isolation-forest scoring identify connections whose behaviour departs from
their peer group, using no labels at all. Outputs at this stage are ranked
suspicion scores, not classifications."

Isolation forest only -- not also an autoencoder. A neural autoencoder
needs a reasonable volume of training examples to avoid simply memorising
(and therefore never flagging) the handful of connections under a single
transformer; with typically 10-30 connections per transformer, an
isolation forest is the appropriate tool at this scale, not a cut corner.
Revisit once training happens over many transformers' pooled connections
rather than one transformer's own handful of peers.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest

from gridintel.module_b.features import ConnectionFeatures

FEATURE_COLUMNS = [
    "fractional_change",
    "daylight_fractional_change",
    "evening_fractional_change",
    "irradiance_correlation",
    "step_sharpness",
    "peer_group_z_score",
    "open_segment_ratio",
]


def compute_suspicion_scores(features: list[ConnectionFeatures], *, seed: int = 0) -> dict[str, float]:
    """Returns connection_id -> suspicion score in [0, 1], higher = more
    anomalous relative to its peers. Not a classification -- a ranking
    signal only, per the module docstring above.
    """
    if len(features) < 3:
        return {f.connection_id: 0.0 for f in features}

    x = np.nan_to_num(
        np.array([[getattr(f, col) for col in FEATURE_COLUMNS] for f in features])
    )
    model = IsolationForest(n_estimators=200, contamination="auto", random_state=seed)
    model.fit(x)
    raw_scores = -model.score_samples(x)  # sklearn: lower score_samples = more anomalous
    lo, hi = raw_scores.min(), raw_scores.max()
    normalized = (raw_scores - lo) / max(hi - lo, 1e-9)
    return {f.connection_id: float(s) for f, s in zip(features, normalized)}
