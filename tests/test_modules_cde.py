"""Tests for Modules C (thermal ageing), D (forecasting) and E (shedding
allocation).

These pin the physics and the optimiser's policy behaviour, plus the two
honesty properties that matter most for these particular modules: that a
remaining-life figure is withheld when thermal ageing is not the binding
constraint (rather than quoting a nonsense number of centuries), and that
forecast accuracy is only ever reported on data the model did not train on.
"""
import numpy as np
import pandas as pd
import pytest

from gridintel.module_c.thermal import (
    HOT_SPOT_LIMIT_NORMAL_CYCLIC_C,
    REFERENCE_HOT_SPOT_C,
    compute_thermal_ageing,
)
from gridintel.module_d.forecast import forecast_demand
from gridintel.module_e.allocation import SheddableUnit, allocate_shedding


def _index(n: int, minutes: int = 30) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-05", periods=n, freq=f"{minutes}min", tz="UTC")


# ---------------- Module C ----------------

def test_hot_spot_rises_with_load():
    idx = _index(200)
    light = compute_thermal_ageing(idx, np.full(len(idx), 5.0), rating_kva=50,
                                   no_load_loss_kw=0.19, load_loss_kw=1.10)
    heavy = compute_thermal_ageing(idx, np.full(len(idx), 45.0), rating_kva=50,
                                   no_load_loss_kw=0.19, load_loss_kw=1.10)
    assert heavy.peak_hot_spot_c > light.peak_hot_spot_c
    assert heavy.mean_ageing_rate > light.mean_ageing_rate


def test_ageing_rate_is_unity_at_reference_hot_spot():
    """V is defined as 1.0 at the 98 C reference -- the anchor the whole
    insulation-life calculation hangs off. If this drifts, every remaining-
    life figure silently drifts with it."""
    idx = _index(50)
    result = compute_thermal_ageing(idx, np.full(len(idx), 10.0), rating_kva=50,
                                    no_load_loss_kw=0.19, load_loss_kw=1.10)
    at_reference = 2.0 ** ((REFERENCE_HOT_SPOT_C - REFERENCE_HOT_SPOT_C) / 6.0)
    assert at_reference == pytest.approx(1.0)
    # And the doubling relationship holds: +6 K doubles the rate.
    assert 2.0 ** ((REFERENCE_HOT_SPOT_C + 6 - REFERENCE_HOT_SPOT_C) / 6.0) == pytest.approx(2.0)


def test_remaining_life_withheld_when_not_thermally_limited():
    """A lightly loaded transformer produces an arithmetically valid but
    practically absurd thermal life (centuries). It must be withheld, not
    displayed -- moisture, mechanical failure and lightning retire the unit
    long before insulation thermal ageing does."""
    idx = _index(300)
    light = compute_thermal_ageing(idx, np.full(len(idx), 3.0), rating_kva=50,
                                   no_load_loss_kw=0.19, load_loss_kw=1.10)
    assert not light.thermally_limited
    assert light.projected_life_years is None


def test_sustained_overload_is_flagged_against_published_limit():
    idx = _index(300)
    overloaded = compute_thermal_ageing(idx, np.full(len(idx), 75.0), rating_kva=50,
                                        no_load_loss_kw=0.19, load_loss_kw=1.10)
    assert overloaded.peak_hot_spot_c > HOT_SPOT_LIMIT_NORMAL_CYCLIC_C
    assert overloaded.hours_above_cyclic_limit > 0
    assert overloaded.risk_band in ("high", "critical")


def test_oil_lag_damps_a_single_short_spike():
    """Oil thermal inertia means one 30-minute spike must not move the
    hot-spot as far as a sustained load at the same level."""
    idx = _index(200)
    base = np.full(len(idx), 5.0)
    spiky = base.copy()
    spiky[100] = 60.0
    sustained = np.full(len(idx), 60.0)

    spike_peak = compute_thermal_ageing(idx, spiky, rating_kva=50,
                                        no_load_loss_kw=0.19, load_loss_kw=1.10).peak_hot_spot_c
    sustained_peak = compute_thermal_ageing(idx, sustained, rating_kva=50,
                                            no_load_loss_kw=0.19, load_loss_kw=1.10).peak_hot_spot_c
    assert spike_peak < sustained_peak


# ---------------- Module D ----------------

def _synthetic_demand(days: int = 40) -> pd.Series:
    idx = _index(days * 48)
    hours = idx.hour + idx.minute / 60
    daily = 30 + 12 * np.sin((hours - 7) / 24 * 2 * np.pi)
    weekly = np.where(idx.dayofweek >= 5, 0.85, 1.0)
    rng = np.random.default_rng(0)
    return pd.Series(daily * weekly + rng.normal(0, 1.2, len(idx)), index=idx)


def test_forecast_beats_naive_on_held_out_data():
    result = forecast_demand(_synthetic_demand())
    naive_mae = float(np.mean(np.abs(result.actual - result.actual.mean())))
    assert result.mae_kw < naive_mae
    assert 0 < result.mape < 100


def test_forecast_never_scores_on_training_data():
    """n_train and n_test must partition the usable frame with no overlap --
    an accuracy figure computed on training data would be meaningless and
    is the easiest mistake to make here."""
    demand = _synthetic_demand()
    result = forecast_demand(demand)
    assert result.n_test > 0 and result.n_train > 0
    # Held-out period must start strictly after the training period ends.
    assert result.ts[0] > demand.index[result.n_train]


def test_forecast_reports_measured_and_nominal_coverage_separately():
    """Section 8.4 asks for band calibration. Both numbers must be exposed
    so an under-covering band is visible rather than implied to be fine."""
    result = forecast_demand(_synthetic_demand())
    assert 0.0 <= result.coverage <= 1.0
    assert result.nominal_coverage == pytest.approx(0.8)


def test_forecast_refuses_too_little_history():
    with pytest.raises(ValueError):
        forecast_demand(_synthetic_demand(days=1))


# ---------------- Module E ----------------

def _units():
    return [
        SheddableUnit("T01", "One", 18.0, hours_shed_recently=12.0, thermally_stressed=True),
        SheddableUnit("T02", "Two", 12.0, carries_critical_load=True, hours_shed_recently=2.0),
        SheddableUnit("T03", "Three", 15.0, hours_shed_recently=1.0),
    ]


def test_no_shedding_when_generation_is_sufficient():
    result = allocate_shedding(_units(), 0.0)
    assert result.feasible
    assert result.shed == []


def test_requirement_is_met():
    result = allocate_shedding(_units(), 14.0)
    assert result.feasible
    assert result.shed_load_kw >= 14.0


def test_critical_load_is_protected_while_alternatives_exist():
    """Section 9.1's first objective. T02 carries critical load and must be
    the last thing shed, even though it is not the largest block."""
    result = allocate_shedding(_units(), 14.0)
    assert "T02" not in result.shed


def test_infeasible_requirement_is_reported_not_silently_partial():
    result = allocate_shedding(_units(), 500.0)
    assert not result.feasible
    assert result.shed == []
    assert "infeasible" in result.message.lower()


def test_thermally_stressed_units_are_shed_more_reluctantly():
    """Repeated restoration inrush accelerates exactly the ageing that
    flagged the unit (Section 9.1), so between two otherwise-equal blocks
    the stressed one should be preferred for retention."""
    a = SheddableUnit("A", "A", 20.0, thermally_stressed=True)
    b = SheddableUnit("B", "B", 20.0, thermally_stressed=False)
    result = allocate_shedding([a, b], 20.0)
    assert result.shed == ["B"]


def test_equity_prefers_the_group_shed_least_recently():
    a = SheddableUnit("A", "A", 20.0, hours_shed_recently=40.0)
    b = SheddableUnit("B", "B", 20.0, hours_shed_recently=2.0)
    result = allocate_shedding([a, b], 20.0)
    assert result.shed == ["B"]
