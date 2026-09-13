"""Section 8.2's evaluation methodology: "The operative metric is precision
at the top of the ranked list -- the proportion of dispatched inspections
that find what the model predicted -- because inspector capacity is the
binding constraint. ... [reported] by cause class, with solar and bypass
reported separately because conflating them is the failure that matters."

Meter failure and full bypass are reported both exactly (did the predicted
cause match) and under a "confusable-aware" precision that also counts a
hit when the two are swapped -- Section 8.2 itself states these are
genuinely hard to tell apart from consumption data alone, and Module B's
weak-supervision stage deliberately splits its vote 50/50 between them
when their shared signature fires (weak_supervision.py). Reporting only
exact-match precision would silently penalise the model for being honest
about that ambiguity; reporting only confusable-aware precision would hide
that the two are still being conflated. Both numbers are given so neither
happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import GroundTruthAnomaly
from gridintel.module_b.pipeline import CaseQueueEntry

CONFUSABLE_GROUPS: list[set[str]] = [{"meter_failure", "full_bypass"}]


def _confusable_match(predicted: str, truth: str) -> bool:
    if predicted == truth:
        return True
    return any(predicted in group and truth in group for group in CONFUSABLE_GROUPS)


@dataclass
class PrecisionEvaluation:
    n_cases: int
    exact_precision: float
    confusable_aware_precision: float
    by_cause: dict[str, dict] = field(default_factory=dict)


def evaluate_case_queue(
    session: Session, scenario_id: str, case_queue: list[CaseQueueEntry], *, k: int | None = None
) -> PrecisionEvaluation:
    truth_rows = session.execute(
        select(GroundTruthAnomaly.connection_id, GroundTruthAnomaly.anomaly_type).where(
            GroundTruthAnomaly.scenario_id == scenario_id
        )
    ).all()
    truth = dict(truth_rows)

    top = case_queue if k is None else case_queue[:k]
    n = len(top)
    if n == 0:
        return PrecisionEvaluation(n_cases=0, exact_precision=float("nan"), confusable_aware_precision=float("nan"))

    exact_hits = sum(1 for e in top if truth.get(e.connection_id) == e.predicted_cause)
    confusable_hits = sum(1 for e in top if _confusable_match(e.predicted_cause, truth.get(e.connection_id, "")))

    by_cause: dict[str, dict] = {}
    for cause in {e.predicted_cause for e in top}:
        subset = [e for e in top if e.predicted_cause == cause]
        hits = sum(1 for e in subset if truth.get(e.connection_id) == cause)
        confusable_subset_hits = sum(1 for e in subset if _confusable_match(cause, truth.get(e.connection_id, "")))
        by_cause[cause] = {
            "n": len(subset),
            "exact_precision": hits / len(subset),
            "confusable_aware_precision": confusable_subset_hits / len(subset),
        }

    return PrecisionEvaluation(
        n_cases=n,
        exact_precision=exact_hits / n,
        confusable_aware_precision=confusable_hits / n,
        by_cause=by_cause,
    )
