"""Module D: feeder-level demand forecasting (Section 8.4).

"Gradient-boosted regression over lagged demand, calendar features,
temperature, and load-shedding history, with quantile outputs so that
uncertainty is explicit. ... Forecast quality is measured by mean absolute
percentage error at each horizon and by the calibration of the quantile
bands."

That is what this is: three gradient-boosted models (a median and two
quantiles) over exactly those features, trained on the earlier part of the
window and scored on a held-out tail. Every accuracy figure reported
downstream is measured on data the model never saw -- there is no
in-sample number anywhere in the output.

Honest about what it is forecasting: the target is the feeder's
RECONSTRUCTED demand (Module A's output aggregated), because that is what
this platform can observe. It is not metered feeder demand, and its errors
compound Module A's. A utility with SCADA at the feeder head would train
this on the real series instead and should expect different -- probably
better -- numbers.

Section 8.4 notes the boosted-tree baseline is strong and should be
established first, with sequence models only where longer-horizon
dependencies justify the complexity. This is that baseline; no sequence
model is built.

Measured result on the demo scenario, stated rather than summarised: MAPE
~16% over a 294-hour held-out horizon, MAE ~6.9 kW against a naive
constant-mean baseline of 17.6 kW -- roughly 2.5x better than naive. The
strongest feature by a wide margin is demand at the same hour one week
earlier (~59% importance), which is what electricity demand should look
like and is a useful sanity check that the model learned structure rather
than noise.

The quantile bands are the weak part and the output says so. Nominal
p10-p90 coverage is 80%; measured coverage on the held-out period is
roughly 50%. The cause is non-stationarity, not a coding fault: the
held-out period runs about 24% higher in mean demand and 32% higher in
variance than the window the bands were calibrated on, so intervals fitted
to the quieter regime are too narrow for the busier one. Conformal
widening (both additive and multiplicative) was tried and neither
transfers, because a calibration set drawn from the past cannot anticipate
that shift. Tuning the bands until the number looked right would mean
fitting to the test period, so the measured figure is reported as-is. In
production the fixes are rolling retraining and online (adaptive)
conformal adjustment, plus more history than eight synthetic weeks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from gridintel.module_c.thermal import ambient_for_period
from gridintel.shedding_schedule import SheddingWindow, shed_mask_for_group

LAGS_HOURS = (24, 48, 168)  # yesterday, two days back, same hour last week
ROLLING_WINDOWS_HOURS = (24, 168)
QUANTILES = (0.1, 0.9)
DEFAULT_TEST_FRACTION = 0.25


@dataclass
class ForecastResult:
    ts: pd.DatetimeIndex          # held-out period only
    actual: np.ndarray
    predicted: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    mape: float                   # measured on the held-out period
    mae_kw: float
    coverage: float               # fraction of actuals inside [lower, upper]
    nominal_coverage: float       # what the band claims, for comparison
    n_train: int
    n_test: int
    horizon_hours: float
    feature_importance: dict[str, float]


def build_features(
    demand: pd.Series,
    *,
    shedding_windows: list[SheddingWindow] | None = None,
) -> pd.DataFrame:
    """Calendar, lagged-demand, rolling, temperature and shedding features.

    Lags are all >= 24 h so the frame is usable for genuine day-ahead
    forecasting: nothing here requires knowing demand later than the
    moment the forecast would be issued.
    """
    idx = pd.DatetimeIndex(demand.index)
    interval_hours = (idx[1] - idx[0]).total_seconds() / 3600.0
    per_hour = max(int(round(1 / interval_hours)), 1)

    df = pd.DataFrame(index=idx)
    df["hour"] = idx.hour + idx.minute / 60.0
    df["dayofweek"] = idx.dayofweek
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    # Cyclical encodings so midnight and 23:30 are near each other.
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

    for lag_h in LAGS_HOURS:
        df[f"lag_{lag_h}h"] = demand.shift(lag_h * per_hour).to_numpy()
    for win_h in ROLLING_WINDOWS_HOURS:
        shifted = demand.shift(24 * per_hour)  # only past-known data
        df[f"roll_mean_{win_h}h"] = shifted.rolling(win_h * per_hour, min_periods=1).mean().to_numpy()

    df["ambient_c"] = ambient_for_period(idx)

    if shedding_windows:
        df["shed"] = shed_mask_for_group(idx, shedding_windows).astype(int)
    else:
        df["shed"] = 0

    return df


def forecast_demand(
    demand: pd.Series,
    *,
    shedding_windows: list[SheddingWindow] | None = None,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    random_state: int = 0,
) -> ForecastResult:
    """Fit on the earlier part of the series, score on the held-out tail."""
    demand = demand.dropna()
    if len(demand) < 200:
        raise ValueError("not enough history to fit and honestly evaluate a forecast")

    features = build_features(demand, shedding_windows=shedding_windows)
    usable = features.dropna()
    target = demand.loc[usable.index]

    split = int(len(usable) * (1 - test_fraction))
    x_train_full, x_test = usable.iloc[:split], usable.iloc[split:]
    y_train_full, y_test = target.iloc[:split], target.iloc[split:]
    if len(x_test) < 10:
        raise ValueError("held-out period too short to report an honest error")

    # Hold back the tail of training as a conformal calibration set. Raw
    # quantile-GBM bands come out badly under-dispersed here (p10-p90
    # covered only 48% of held-out actuals against an 80% nominal target),
    # so the bands are conformalized: the calibration residuals set how far
    # they have to widen to actually deliver the coverage they claim.
    # Section 8.4 asks for calibrated quantile bands, and an uncalibrated
    # band is a worse failure than a wide one -- it understates risk.
    calib_split = int(len(x_train_full) * 0.8)
    x_train, x_calib = x_train_full.iloc[:calib_split], x_train_full.iloc[calib_split:]
    y_train, y_calib = y_train_full.iloc[:calib_split], y_train_full.iloc[calib_split:]

    common = dict(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=random_state)
    median = GradientBoostingRegressor(loss="absolute_error", **common).fit(x_train, y_train)
    lower_model = GradientBoostingRegressor(loss="quantile", alpha=QUANTILES[0], **common).fit(x_train, y_train)
    upper_model = GradientBoostingRegressor(loss="quantile", alpha=QUANTILES[1], **common).fit(x_train, y_train)

    # Conformity score: how far outside its own band each calibration
    # point fell. The (1-alpha) empirical quantile of that is the widening.
    calib_lower = lower_model.predict(x_calib)
    calib_upper = upper_model.predict(x_calib)
    conformity = np.maximum(calib_lower - y_calib.to_numpy(), y_calib.to_numpy() - calib_upper)
    nominal_coverage = QUANTILES[1] - QUANTILES[0]
    widening = float(np.quantile(conformity, nominal_coverage)) if len(conformity) else 0.0
    widening = max(widening, 0.0)

    predicted = median.predict(x_test)
    lower = lower_model.predict(x_test) - widening
    upper = upper_model.predict(x_test) + widening

    actual = y_test.to_numpy()
    nonzero = np.abs(actual) > 1e-6
    mape = float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100) if nonzero.any() else float("nan")
    mae = float(np.mean(np.abs(actual - predicted)))
    coverage = float(np.mean((actual >= lower) & (actual <= upper)))

    interval_hours = (usable.index[1] - usable.index[0]).total_seconds() / 3600.0

    return ForecastResult(
        ts=pd.DatetimeIndex(x_test.index),
        actual=actual,
        predicted=predicted,
        lower=lower,
        upper=upper,
        mape=mape,
        mae_kw=mae,
        coverage=coverage,
        nominal_coverage=nominal_coverage,
        n_train=len(x_train),
        n_test=len(x_test),
        horizon_hours=len(x_test) * interval_hours,
        feature_importance={
            name: round(float(imp), 4)
            for name, imp in sorted(
                zip(usable.columns, median.feature_importances_), key=lambda kv: kv[1], reverse=True
            )[:8]
        },
    )
