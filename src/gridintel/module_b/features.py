"""Per-connection features built directly from Section 8.2's discriminating-
signature table:

| Cause          | Signature                                                |
|----------------|-----------------------------------------------------------|
| Rooftop solar  | gradual onset; daylight-hours reduction; irradiance corr.; evening preserved |
| Battery added  | evening also falls; post-restoration demand spike          |
| Bypass/tamper  | step change; no weather correlation; transformer load unchanged; often clustered |
| Meter failure  | abrupt to near zero; no transformer-level change; isolated |
| Vacancy        | fall to zero; purchasing stops; customer record often follows |
| Genuine reduction | proportional; consistent across a wide population        |

Every feature here is built from what a production deployment would
actually have: Module A's reconstruction (not privileged ground truth),
the connection's own vending activity, its `status` field, and real public
irradiance data. There is no changepoint detection -- baseline vs. recent
periods are a fixed fraction of the evaluation window (first/last 20% by
default), which is a real simplification: a mistimed anomaly onset close
to either boundary weakens the signal this captures. A fuller version
would detect the changepoint itself rather than assume its rough location.

A more fundamental limitation, confirmed with real numbers while building
this rather than assumed: `daylight_fractional_change` and
`evening_fractional_change` are structurally weak for solar detection
specifically, because Module A's segment reconstruction (segment_
reconstruction.py) can only vary the OVERALL SCALE of a connection's
consumption per segment -- it always redistributes that scale using the
SAME fixed archetype diurnal shape, never a changed one. A true solar
adopter's real signature is a SHAPE change (daylight collapses, evening is
untouched) -- verified on this generator's own ground truth: one solar
case showed a true daylight change of -99.7% against a true evening change
of +4.9% (noise). Module A's reconstruction of that same connection showed
-84% for BOTH, because a single scaled-down copy of the same diurnal
template cannot represent "only daylight changed" at all. This is why
solar recall is the weakest part of Module B's results (see README) --
it is an information gap between what Module A can output and what this
discrimination needs, not a threshold to tune. Closing it would mean
extending Module A to support intra-day shape adjustment, which vending
events alone may not carry enough information to identify either -- this
is flagged as a real open problem, not solved here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DAYLIGHT_HOURS = (9, 15)
EVENING_HOURS = (18, 22)
EPS = 1e-9


@dataclass
class ConnectionFeatures:
    connection_id: str
    baseline_mean_kw: float
    recent_mean_kw: float
    fractional_change: float
    daylight_fractional_change: float
    evening_fractional_change: float
    irradiance_correlation: float
    step_sharpness: float
    zero_purchase_activity_recent: bool
    connection_inactive: bool
    open_segment_ratio: float  # current gap since last purchase, vs this connection's own typical gap
    peer_group_z_score: float = 0.0  # filled in by the transformer-level orchestrator

    @property
    def estimated_recoverable_kw(self) -> float:
        return max(self.baseline_mean_kw - self.recent_mean_kw, 0.0)


def _mean_in(series: pd.Series, mask: pd.Series, sub_index: pd.DatetimeIndex) -> float:
    values = series.loc[sub_index][mask.loc[sub_index]]
    return float(values.mean()) if len(values) else float("nan")


def compute_connection_features(
    connection_id: str,
    recon_kw: pd.Series,
    purchase_ts: pd.DatetimeIndex,
    *,
    connection_status: str,
    irradiance_w_m2: pd.Series | None = None,
    baseline_frac: float = 0.2,
    recent_frac: float = 0.2,
) -> ConnectionFeatures:
    recon_kw = recon_kw.dropna()
    idx = recon_kw.index
    n = len(idx)
    baseline_idx = idx[: int(n * baseline_frac)]
    recent_idx = idx[int(n * (1 - recent_frac)) :]

    baseline_mean = float(recon_kw.loc[baseline_idx].mean())
    recent_mean = float(recon_kw.loc[recent_idx].mean())
    fractional_change = (recent_mean - baseline_mean) / max(baseline_mean, EPS)

    hours = idx.hour
    daylight_mask = pd.Series((hours >= DAYLIGHT_HOURS[0]) & (hours < DAYLIGHT_HOURS[1]), index=idx)
    evening_mask = pd.Series((hours >= EVENING_HOURS[0]) & (hours < EVENING_HOURS[1]), index=idx)

    baseline_daylight = _mean_in(recon_kw, daylight_mask, baseline_idx)
    recent_daylight = _mean_in(recon_kw, daylight_mask, recent_idx)
    daylight_fractional_change = (recent_daylight - baseline_daylight) / max(baseline_daylight, EPS)

    baseline_evening = _mean_in(recon_kw, evening_mask, baseline_idx)
    recent_evening = _mean_in(recon_kw, evening_mask, recent_idx)
    evening_fractional_change = (recent_evening - baseline_evening) / max(baseline_evening, EPS)

    irradiance_correlation = 0.0
    if irradiance_w_m2 is not None:
        daylight_series = recon_kw.loc[recent_idx][daylight_mask.loc[recent_idx]]
        daily_daylight = daylight_series.resample("1D").mean()
        daily_irradiance = irradiance_w_m2.reindex(idx).loc[recent_idx][daylight_mask.loc[recent_idx]].resample("1D").mean()
        common = pd.concat([daily_daylight, daily_irradiance], axis=1).dropna()
        if len(common) >= 5 and common.iloc[:, 0].std() > EPS and common.iloc[:, 1].std() > EPS:
            irradiance_correlation = float(common.iloc[:, 0].corr(common.iloc[:, 1]))

    daily = recon_kw.resample("1D").mean().dropna()
    step_sharpness = 0.0
    if len(daily) > 3:
        diffs = daily.diff().dropna().abs()
        if len(diffs) > 1:
            typical = float(diffs.median())
            step_sharpness = float(diffs.max()) / max(typical, EPS)

    recent_start_ts = recent_idx[0] if len(recent_idx) else idx[-1]
    zero_purchase_activity_recent = bool((purchase_ts >= recent_start_ts).sum() == 0)

    # Direct implementation of Section 8.2's "sustained zero consumption
    # with an active transformer implies meter failure or bypass": a
    # meter that stops decrementing balance (rather than a customer who
    # consumes less) shows up as an abnormally long gap since a purchase
    # -- available immediately from raw purchase timestamps, without
    # waiting for Module A's segment-averaged reconstruction to
    # (necessarily) smear a mid-segment collapse across the whole segment
    # it falls in. "Abnormal" is judged against gaps from the BASELINE
    # period only (the first `baseline_frac` of the window, assumed
    # anomaly-free) so the anomalous gap itself never dilutes what counts
    # as typical. The longest gap is taken from anywhere after the
    # baseline period through the window's end -- not just whatever gap is
    # still open at the end -- because a customer can resume purchasing
    # (even a token habitual top-up) after an anomalous silence without
    # that silence having been any less real (confirmed: a real meter-
    # failure case in this generator's own output had exactly this shape).
    # Two guards against a noisy ratio from thin data, both confirmed
    # necessary by testing: (1) fewer than 3 baseline purchases (2 gaps)
    # gives a typical-gap estimate too unstable to trust -- a single short
    # baseline gap by chance made ordinary later gaps look like a multiple
    # of it; (2) a large RATIO over a small ABSOLUTE gap (e.g. 3 days vs a
    # 1-day typical gap) is not what "sustained silence" means and fired
    # on high-frequency-purchase archetypes far too often without either
    # guard.
    open_segment_ratio = 0.0
    sorted_purchases = purchase_ts.sort_values()
    baseline_end_ts = baseline_idx[-1] if len(baseline_idx) else idx[0]
    baseline_purchases = sorted_purchases[sorted_purchases <= baseline_end_ts]
    baseline_gap_days = baseline_purchases.to_series().diff().dropna().dt.total_seconds() / 86400
    typical_gap_days = float(baseline_gap_days.median()) if len(baseline_gap_days) >= 2 else float("nan")

    if typical_gap_days and typical_gap_days > EPS:
        anchor = baseline_purchases[-1] if len(baseline_purchases) else idx[0]
        markers = list(sorted_purchases[sorted_purchases > baseline_end_ts]) + [idx[-1]]
        gap_days = []
        prev = anchor
        for marker in markers:
            gap_days.append((marker - prev).total_seconds() / 86400)
            prev = marker
        max_gap_days = max(gap_days) if gap_days else 0.0
        if max_gap_days >= 7.0:
            open_segment_ratio = max_gap_days / typical_gap_days

    return ConnectionFeatures(
        connection_id=connection_id,
        baseline_mean_kw=baseline_mean,
        recent_mean_kw=recent_mean,
        fractional_change=fractional_change,
        daylight_fractional_change=daylight_fractional_change,
        evening_fractional_change=evening_fractional_change,
        irradiance_correlation=irradiance_correlation,
        step_sharpness=step_sharpness,
        zero_purchase_activity_recent=zero_purchase_activity_recent,
        connection_inactive=(connection_status != "active"),
        open_segment_ratio=open_segment_ratio,
    )


def assign_peer_group_z_scores(features: list[ConnectionFeatures]) -> None:
    """In place: z-score each connection's fractional_change against the
    robust (median/MAD) distribution of its peers' fractional_change --
    catches "Genuine demand reduction: proportional... consistent across a
    wide population" (low |z|) versus an idiosyncratic single-connection
    change (high |z|).
    """
    if len(features) < 3:
        for f in features:
            f.peer_group_z_score = 0.0
        return
    values = np.array([f.fractional_change for f in features])
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median))) * 1.4826  # normal-consistent MAD scale
    for f in features:
        f.peer_group_z_score = (f.fractional_change - median) / max(mad, EPS)
