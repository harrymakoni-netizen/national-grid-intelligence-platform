"""Weak-supervision stage (Section 8.2): "Labelling functions encoding
domain rules -- irradiance correlation implies solar; sustained zero
consumption with an active transformer implies meter failure or bypass --
are combined into probabilistic labels."

This is a simplified combiner, not a learned label model (e.g. Snorkel's
generative model) -- each labelling function casts a vote with a strength
for one or more candidate causes, votes are summed per cause, and the
top cause is reported with a confidence normalised by the total vote mass.
A full probabilistic label-aggregation model is deferred until there is
enough real labelled volume (Section 8.2's stage 3) to make learning label
weights meaningful; until then, a transparent weighted vote is easier to
audit and explain to a utility engineer than a black-box combiner would be
-- which matters, per Section 10.3's evidentiary requirements.

Meter failure and full bypass are DELIBERATELY given near-equal votes when
their shared signature fires (Section 8.2 lists them as genuinely
confusable from consumption data alone) -- pretending otherwise would be
dishonest confidence, not a better model. "Battery storage added" (Section
8.2's variant of solar where evening also falls) has no separate label in
this generator's AnomalyType and is not distinguished here; it would
collapse into SOLAR_ADOPTION, which is stated rather than hidden.
"""
from __future__ import annotations

from dataclasses import dataclass

from gridintel.db.models import AnomalyType
from gridintel.module_b.features import ConnectionFeatures

NORMAL = "normal"  # not an AnomalyType -- "nothing worth queuing" outcome


@dataclass
class WeakLabel:
    connection_id: str
    predicted_cause: str
    confidence: float
    votes: dict[str, float]


def _lf_solar(f: ConnectionFeatures) -> dict[str, float]:
    # Evening preserved is a REQUIRED gate, not just a strength booster: a
    # connection whose evening consumption collapsed just as much as its
    # daylight consumption has not adopted solar (without storage) -- it
    # has some other, much larger problem, and a spurious irradiance
    # correlation from Module A's reconstruction noise must not override
    # that. This was a real bug: without the gate, total-collapse cases
    # (vacancy, failure) were being misclassified as solar.
    if (
        f.daylight_fractional_change < -0.15
        and f.irradiance_correlation < -0.15
        and f.evening_fractional_change > f.daylight_fractional_change * 0.75
    ):
        strength = min(abs(f.daylight_fractional_change) * 2, 1.0) * min(abs(f.irradiance_correlation) * 2, 1.0)
        return {AnomalyType.SOLAR_ADOPTION.value: strength}
    return {}


def _lf_vacancy(f: ConnectionFeatures) -> dict[str, float]:
    # A customer-system inactive flag is direct evidence on its own
    # (Section 8.2: "in most cases a corresponding record in customer
    # systems") -- requiring zero_purchase_activity_recent as well was too
    # strict: a habitual top-up can still land in the recent window purely
    # on calendar timing even after physical consumption has collapsed
    # (gridsynth's own purchasing model can do this), so it must not gate
    # out an otherwise clear case.
    if f.connection_inactive and f.fractional_change < -0.5:
        return {AnomalyType.VACANCY.value: 0.9}
    if f.fractional_change < -0.8 and f.zero_purchase_activity_recent:
        return {AnomalyType.VACANCY.value: 0.5}
    return {}


def _lf_failure_or_full_bypass(f: ConnectionFeatures) -> dict[str, float]:
    if f.fractional_change < -0.85 and f.step_sharpness > 2.0 and not f.connection_inactive:
        # Genuinely ambiguous from consumption data alone -- split evenly.
        return {AnomalyType.METER_FAILURE.value: 0.5, AnomalyType.FULL_BYPASS.value: 0.5}
    return {}


def _lf_sustained_silence(f: ConnectionFeatures) -> dict[str, float]:
    """Section 8.2's own named heuristic: "sustained zero consumption with
    an active transformer implies meter failure or bypass." An abnormally
    long gap since the last purchase (relative to this connection's own
    history) fires even when Module A's segment-averaged reconstruction
    hasn't caught up to a mid-segment collapse yet -- see features.py's
    open_segment_ratio docstring for why this signal is more direct.
    """
    if f.open_segment_ratio > 4.0 and not f.connection_inactive:
        strength = min((f.open_segment_ratio - 4.0) / 6.0, 1.0)
        return {AnomalyType.METER_FAILURE.value: strength * 0.5, AnomalyType.FULL_BYPASS.value: strength * 0.5}
    return {}


def _lf_partial_bypass(f: ConnectionFeatures) -> dict[str, float]:
    if (
        -0.85 < f.fractional_change < -0.2
        and f.step_sharpness > 1.5
        and f.irradiance_correlation > -0.15
        and not f.zero_purchase_activity_recent
        and not f.connection_inactive
    ):
        strength = min(abs(f.fractional_change) * 1.2, 1.0)
        return {AnomalyType.PARTIAL_BYPASS.value: strength}
    return {}


def _lf_genuine_reduction(f: ConnectionFeatures) -> dict[str, float]:
    if abs(f.peer_group_z_score) < 1.0 and f.fractional_change < -0.05:
        return {NORMAL: 0.6}
    return {}


LABELING_FUNCTIONS = [
    _lf_solar,
    _lf_vacancy,
    _lf_failure_or_full_bypass,
    _lf_sustained_silence,
    _lf_partial_bypass,
    _lf_genuine_reduction,
]


def classify(features: ConnectionFeatures) -> WeakLabel:
    votes: dict[str, float] = {}
    for lf in LABELING_FUNCTIONS:
        for cause, strength in lf(features).items():
            votes[cause] = votes.get(cause, 0.0) + strength

    if not votes:
        return WeakLabel(features.connection_id, NORMAL, 0.0, votes)

    # "Is this anomalous at all" and "which anomaly" are resolved as two
    # separate decisions, not one flat plurality vote. A flat vote lets a
    # genuinely ambiguous case (e.g. meter_failure/full_bypass splitting
    # 0.48/0.48, correctly reflecting real uncertainty per Section 8.2) lose
    # to a single-cause hypothesis with LESS total supporting evidence
    # (e.g. normal at 0.6) purely because it wasn't split across two
    # labels. Comparing total anomaly mass against normal mass first fixes
    # that without abandoning the honest split once something is flagged.
    anomaly_votes = {k: v for k, v in votes.items() if k != NORMAL}
    anomaly_mass = sum(anomaly_votes.values())
    normal_mass = votes.get(NORMAL, 0.0)

    if not anomaly_votes or anomaly_mass <= normal_mass:
        denom = anomaly_mass + normal_mass
        confidence = normal_mass / denom if denom > 0 else 0.0
        return WeakLabel(features.connection_id, NORMAL, confidence, votes)

    predicted_cause = max(anomaly_votes, key=anomaly_votes.get)
    confidence = anomaly_votes[predicted_cause] / anomaly_mass
    return WeakLabel(features.connection_id, predicted_cause, confidence, votes)
