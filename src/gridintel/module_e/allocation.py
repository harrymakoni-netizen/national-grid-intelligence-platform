"""Module E: load-shedding allocation (Section 9.1).

Section 9.1 is unusually direct about what this is and is not:

  "The allocation itself is a constrained optimisation problem, not a
  learning problem ... Presenting the optimiser itself as artificial
  intelligence would be inaccurate and would be identified as such by any
  competent engineer reviewing the proposal."

So this is a mixed-integer program solved with scipy.optimize.milp, and
nothing here is described as AI anywhere it surfaces. The learning
contribution sits upstream in Module D's forecast, which supplies the
demand figure this consumes.

Decision: which transformers to shed in a given half-hour block, given a
shedding requirement in kW. Binary per transformer -- a feeder is either
shed or it is not; you cannot shed 40% of a feeder.

Objective (minimised), assembled from Section 9.1's stated priorities:

  - protection of critical load: a large penalty weight per transformer
    carrying hospital/water/telecoms load, so the optimiser sheds these
    only when nothing else closes the gap
  - equity of cumulative outage hours: penalty proportional to how many
    hours each group has ALREADY been shed over the rolling window, which
    is what stops the same suburbs absorbing every block
  - transformer thermal stress: penalty on units Module C has flagged,
    because repeated restoration inrush accelerates exactly the ageing
    that flagged them
  - revenue preservation: a light penalty proportional to load, breaking
    ties toward shedding less revenue-generating demand

Constraint: total shed load must meet or exceed the requirement. If the
requirement exceeds the total available load, the problem is infeasible
and that is reported rather than silently returning a partial answer.

The weights below are policy, not physics. They encode a utility's
priorities and a real deployment would have them set by the utility, in
writing, rather than by this file. They are exposed as arguments for that
reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import LinearConstraint, milp, Bounds

# Policy weights. Higher = more reluctant to shed. Critical load is
# deliberately an order of magnitude above the others so it is shed only
# when the requirement cannot otherwise be met.
WEIGHT_CRITICAL = 100.0
WEIGHT_EQUITY = 1.0        # per hour already shed in the rolling window
WEIGHT_THERMAL_STRESS = 8.0
WEIGHT_REVENUE = 0.02      # per kW of load


@dataclass
class SheddableUnit:
    transformer_id: str
    name: str
    load_kw: float
    carries_critical_load: bool = False
    hours_shed_recently: float = 0.0
    thermally_stressed: bool = False


@dataclass
class AllocationResult:
    requirement_kw: float
    shed: list[str]
    retained: list[str]
    shed_load_kw: float
    feasible: bool
    message: str
    per_unit: list[dict] = field(default_factory=list)

    @property
    def overshoot_kw(self) -> float:
        return self.shed_load_kw - self.requirement_kw


def _unit_cost(u: SheddableUnit) -> float:
    cost = WEIGHT_REVENUE * u.load_kw
    cost += WEIGHT_EQUITY * u.hours_shed_recently
    if u.carries_critical_load:
        cost += WEIGHT_CRITICAL
    if u.thermally_stressed:
        cost += WEIGHT_THERMAL_STRESS
    return cost


def allocate_shedding(
    units: list[SheddableUnit],
    requirement_kw: float,
    *,
    weight_critical: float = WEIGHT_CRITICAL,
    weight_equity: float = WEIGHT_EQUITY,
    weight_thermal: float = WEIGHT_THERMAL_STRESS,
    weight_revenue: float = WEIGHT_REVENUE,
) -> AllocationResult:
    """Choose the set of transformers to shed that meets the requirement at
    least total policy cost. Deterministic mixed-integer program.
    """
    if not units:
        return AllocationResult(requirement_kw, [], [], 0.0, False, "no sheddable units supplied")

    if requirement_kw <= 0:
        return AllocationResult(
            requirement_kw, [], [u.transformer_id for u in units], 0.0, True,
            "no shedding required: generation meets forecast demand",
        )

    total_available = sum(u.load_kw for u in units)
    if requirement_kw > total_available + 1e-9:
        return AllocationResult(
            requirement_kw, [], [u.transformer_id for u in units], 0.0, False,
            f"infeasible: requirement {requirement_kw:.1f} kW exceeds total sheddable load "
            f"{total_available:.1f} kW. Shedding every feeder would still not close the gap.",
        )

    costs = []
    for u in units:
        c = weight_revenue * u.load_kw + weight_equity * u.hours_shed_recently
        if u.carries_critical_load:
            c += weight_critical
        if u.thermally_stressed:
            c += weight_thermal
        costs.append(c)

    loads = np.array([u.load_kw for u in units], dtype=float)
    # Meet or exceed the requirement.
    constraint = LinearConstraint(loads.reshape(1, -1), lb=requirement_kw, ub=np.inf)

    result = milp(
        c=np.array(costs, dtype=float),
        constraints=[constraint],
        integrality=np.ones(len(units)),
        bounds=Bounds(lb=0, ub=1),
    )

    if not result.success:
        return AllocationResult(
            requirement_kw, [], [u.transformer_id for u in units], 0.0, False,
            f"solver could not find an allocation: {result.message}",
        )

    chosen = np.round(result.x).astype(int)
    shed = [u.transformer_id for u, s in zip(units, chosen) if s == 1]
    retained = [u.transformer_id for u, s in zip(units, chosen) if s == 0]
    shed_load = float(loads[chosen == 1].sum())

    per_unit = [
        {
            "transformer_id": u.transformer_id,
            "name": u.name,
            "load_kw": round(u.load_kw, 2),
            "shed": bool(s),
            "carries_critical_load": u.carries_critical_load,
            "thermally_stressed": u.thermally_stressed,
            "hours_shed_recently": round(u.hours_shed_recently, 1),
            "policy_cost": round(float(c), 2),
        }
        for u, s, c in zip(units, chosen, costs)
    ]

    return AllocationResult(
        requirement_kw=requirement_kw,
        shed=shed,
        retained=retained,
        shed_load_kw=shed_load,
        feasible=True,
        message=(
            f"shedding {len(shed)} of {len(units)} transformers for {shed_load:.1f} kW "
            f"against a {requirement_kw:.1f} kW requirement"
        ),
        per_unit=per_unit,
    )
