"""Converts true (post-shedding) consumption into discrete prepaid token
purchase events -- the inverse of what Module A (consumption reconstruction)
has to solve, and the component flagged most loudly in the design review as
the weakest-grounded part of the whole pipeline.

There is no public dataset pairing real interval consumption with real
prepaid vending events (if one existed, Module A's core problem would
already be solved), so this purchasing-behaviour model is necessarily
invented rather than fitted. It is built to reproduce the *qualitative*
properties Section 12.1 asks for -- income-cycle clustering, variable
purchase sizes, erratic timing, and a hard cumulative-purchases-bound-
cumulative-consumption constraint -- not to reproduce Zimbabwean purchasing
behaviour quantitatively. Treat every purchasing-side parameter here as
provisional, and re-fit this model (not just re-validate it) the moment any
real vending extract becomes available, however small.

Mechanism: a per-connection running token balance (kWh) is depleted by true
consumption each interval. If the balance is exhausted, actual consumption
is capped at the balance (a real prepaid meter self-disconnects) -- this is
what produces genuine, purchase-driven gaps in consumption independent of
load-shedding or any injected anomaly. Purchase probability rises as
"runway" (balance / recent average daily draw) shrinks and again near a
per-connection payday phase; purchase size is larger and more likely near
payday, smaller and more erratic otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gridintel.db.models import ConnectionArchetype

# PLACEHOLDER: representative domestic/commercial/industrial tariff rates,
# USD-equivalent per kWh. Confirm against ZERA-approved ZETDC tariff schedule.
TARIFF_RATE_USD_PER_KWH = {
    ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: 0.10,
    ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: 0.12,
    ConnectionArchetype.SMALL_COMMERCIAL: 0.15,
    ConnectionArchetype.INDUSTRIAL: 0.11,
}

DENOMINATIONS_USD = [1, 2, 5, 10, 20, 50, 100]

PURCHASE_PARAMS = {
    ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: dict(
        payday_period_days=7,  # informal/day-labour income, weekly cycle
        payday_window_days=1.5,
        payday_boost=3.0,
        threshold_days=2.0,
        base_impulse_prob=0.03,
        max_prob_per_interval=0.9,
        purchase_size_days_of_supply=(2, 6),  # off-payday top-up size
        payday_size_days_of_supply=(5, 12),
    ),
    ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: dict(
        payday_period_days=30,
        payday_window_days=3,
        payday_boost=2.5,
        threshold_days=4.0,
        base_impulse_prob=0.02,
        max_prob_per_interval=0.9,
        purchase_size_days_of_supply=(4, 10),
        payday_size_days_of_supply=(15, 35),
    ),
    ConnectionArchetype.SMALL_COMMERCIAL: dict(
        payday_period_days=30,
        payday_window_days=4,
        payday_boost=1.8,
        threshold_days=5.0,
        base_impulse_prob=0.03,
        max_prob_per_interval=0.9,
        purchase_size_days_of_supply=(5, 12),
        payday_size_days_of_supply=(15, 30),
    ),
    ConnectionArchetype.INDUSTRIAL: dict(
        payday_period_days=30,
        payday_window_days=5,
        payday_boost=1.3,
        threshold_days=7.0,
        base_impulse_prob=0.05,
        max_prob_per_interval=0.95,
        purchase_size_days_of_supply=(10, 20),
        payday_size_days_of_supply=(20, 35),
    ),
}


@dataclass
class PurchaseEvent:
    connection_id: str
    ts: pd.Timestamp
    amount: float
    currency: str
    kwh_purchased: float
    tariff_band: str
    vending_channel: str


def _snap_to_denomination(amount: float, rng: np.random.Generator) -> float:
    if rng.random() < 0.6:
        idx = int(np.argmin(np.abs(np.array(DENOMINATIONS_USD) - amount)))
        return float(DENOMINATIONS_USD[idx])
    return round(amount, 2)


def simulate_connection(
    *,
    connection_id: str,
    archetype: ConnectionArchetype,
    tariff_band: str,
    true_kw: np.ndarray,
    timestamps: pd.DatetimeIndex,
    interval_minutes: int,
    seed: int,
) -> tuple[np.ndarray, list[PurchaseEvent]]:
    """Returns (actual_kw after balance-exhaustion capping, purchase events)."""
    rng = np.random.default_rng(seed)
    params = PURCHASE_PARAMS[archetype]
    tariff_rate = TARIFF_RATE_USD_PER_KWH[archetype]
    interval_hours = interval_minutes / 60.0
    intervals_per_day = int(24 * 60 / interval_minutes)

    wanted_kwh = true_kw * interval_hours
    avg_daily_kwh = float(np.mean(wanted_kwh)) * intervals_per_day
    avg_daily_kwh = max(avg_daily_kwh, 1e-6)

    phase = rng.integers(0, params["payday_period_days"])
    balance = rng.uniform(1, 3) * avg_daily_kwh  # starting stock

    actual_kwh = np.zeros(len(wanted_kwh))
    events: list[PurchaseEvent] = []

    trailing_window = min(intervals_per_day * 7, len(wanted_kwh))
    for i in range(len(wanted_kwh)):
        supplied = min(wanted_kwh[i], balance)
        actual_kwh[i] = supplied
        balance -= supplied

        lo = max(0, i - trailing_window)
        recent_avg_daily = max(float(np.mean(wanted_kwh[lo : i + 1])) * intervals_per_day, 1e-6)

        day_index = timestamps[i].value // (interval_minutes * 60 * 1_000_000_000) // intervals_per_day
        days_to_payday = min(
            (int(day_index) - phase) % params["payday_period_days"],
            params["payday_period_days"] - ((int(day_index) - phase) % params["payday_period_days"]),
        )
        near_payday = days_to_payday <= params["payday_window_days"]

        runway_days = balance / recent_avg_daily
        prob = params["base_impulse_prob"]
        if runway_days < params["threshold_days"]:
            urgency = (params["threshold_days"] - runway_days) / params["threshold_days"]
            prob += urgency * 0.8
        if near_payday:
            prob *= params["payday_boost"]
        if balance <= 0:
            prob = max(prob, 0.5)
        prob = min(prob, params["max_prob_per_interval"])

        if rng.random() < prob:
            lo_days, hi_days = (
                params["payday_size_days_of_supply"] if near_payday else params["purchase_size_days_of_supply"]
            )
            days_of_supply = rng.uniform(lo_days, hi_days)
            kwh_purchased = days_of_supply * recent_avg_daily * rng.lognormal(0, 0.15)
            kwh_purchased = max(kwh_purchased, 0.5)
            balance += kwh_purchased

            raw_amount = kwh_purchased * tariff_rate
            amount = _snap_to_denomination(raw_amount, rng)
            # keep kwh_purchased consistent with the (possibly snapped) amount actually paid
            kwh_purchased = amount / tariff_rate

            events.append(
                PurchaseEvent(
                    connection_id=connection_id,
                    ts=timestamps[i],
                    amount=amount,
                    currency="USD",
                    kwh_purchased=kwh_purchased,
                    tariff_band=tariff_band,
                    vending_channel=rng.choice(["mobile_app", "agent", "ussd", "web"]),
                )
            )

    return actual_kwh, events


def generate_vending_events(
    true_consumption: pd.DataFrame,
    connection_archetypes: dict[str, ConnectionArchetype],
    connection_tariff_bands: dict[str, str],
    *,
    interval_minutes: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Runs the purchase simulation for every connection.

    Returns (updated_consumption, vending_events) where updated_consumption
    has the same shape as the input but with `kw` capped by prepaid balance
    exhaustion, and vending_events is a long DataFrame of purchase records.
    """
    rng = np.random.default_rng(seed)
    all_events: list[PurchaseEvent] = []
    updated_frames = []

    for connection_id, group in true_consumption.groupby("connection_id"):
        group = group.sort_values("ts")
        archetype = connection_archetypes[connection_id]
        tariff_band = connection_tariff_bands[connection_id]
        timestamps = pd.DatetimeIndex(group["ts"])
        conn_seed = int(rng.integers(0, 2**32 - 1))

        actual_kwh_per_interval, events = simulate_connection(
            connection_id=connection_id,
            archetype=archetype,
            tariff_band=tariff_band,
            true_kw=group["kw"].to_numpy(),
            timestamps=timestamps,
            interval_minutes=interval_minutes,
            seed=conn_seed,
        )
        interval_hours = interval_minutes / 60.0
        updated = group.copy()
        updated["kw"] = actual_kwh_per_interval / interval_hours
        updated_frames.append(updated)
        all_events.extend(events)

    updated_consumption = pd.concat(updated_frames, ignore_index=True)
    events_df = pd.DataFrame(
        [
            {
                "connection_id": e.connection_id,
                "ts": e.ts,
                "amount": e.amount,
                "currency": e.currency,
                "kwh_purchased": e.kwh_purchased,
                "tariff_band": e.tariff_band,
                "vending_channel": e.vending_channel,
            }
            for e in all_events
        ]
    )
    return updated_consumption, events_df
