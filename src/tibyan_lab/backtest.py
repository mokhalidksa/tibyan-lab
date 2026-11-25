"""Rolling-origin backtest of a seasonal-naive baseline and a LightGBM model.

Output follows tibyan-lab/forecast-check@1 in tibyan-web's docs/lab-api.md.

How it works
------------
* Folds: the last `folds * horizon` rows are split into `folds` test windows of
  `horizon` rows. Each fold trains only on the rows before its window.
* Baseline: seasonal naive. Each forecast repeats the value from one season earlier
  (for a series with no season, the last value).
* Model: LightGBM on the seasonal difference d[t] = z[t] - z[t - s], where z is the
  log of the series when every value is positive (so growth is multiplicative) and
  the series itself otherwise. Features are d[t-1..t-3], d[t-s], the mean of the last
  season of d, and calendar fields. Forecasts are recursive: each predicted step feeds
  the next. Modelling the change rather than the level lets the trees follow a trend.
* Errors: MAE, and MAPE in percent (null for a window containing a zero). The overall
  figures pool every test point of every fold.
* Interval: the 10th and 90th percentiles of the model's backtest errors, applied to
  the final forecast (in log space when the model ran in log space): an 80% interval.
"""

from __future__ import annotations

import os
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import errors
from .settings import Settings
from .validation import Series

INTERVAL = 0.8
HISTORY_POINTS = 500


def default_horizon(season: int) -> int:
    return season if season > 1 else 3


def max_horizon(season: int) -> int:
    return 2 * max(season, 3)


def min_rows(season: int, horizon: int, folds: int) -> int:
    """Two seasons of history to build the first features, a little to learn from, then the test windows."""
    s = max(season, 1)
    return max(2 * s, s + 3) + max(12, s) + folds * horizon


def _calendar(dates: pd.DatetimeIndex, frequency: str) -> np.ndarray:
    base = frequency.split("-")[0].lstrip("0123456789").upper()
    if base in {"H", "BH"}:
        columns = [dates.hour, dates.dayofweek]
    elif base in {"MIN", "T", "S"}:
        columns = [dates.minute, dates.hour]
    elif base in {"D", "B", "C"}:
        columns = [dates.dayofweek, dates.month, dates.day]
    elif base == "W":
        columns = [dates.isocalendar().week.to_numpy(), dates.month]
    elif base.startswith(("M", "BM", "SM")):
        columns = [dates.month]
    elif base.startswith(("Q", "BQ")):
        columns = [dates.quarter]
    else:
        columns = []
    if not columns:
        return np.zeros((len(dates), 0))
    return np.column_stack([np.asarray(column, dtype=float) for column in columns])


class _Model:
    """The LightGBM forecaster for one training window."""

    def __init__(self, z: np.ndarray, calendar: np.ndarray, season: int, settings: Settings) -> None:
        self.season = max(season, 1)
        self.settings = settings
        self.first = max(2 * self.season, self.season + 3)
        self.z = z
        self.calendar = calendar

    def _features(self, d: np.ndarray, t: int) -> list[float]:
        s = self.season
        row = [d[t - 1], d[t - 2], d[t - 3]]
        if s > 1:
            row.append(d[t - s])
            row.append(float(np.mean(d[t - s : t])))
        else:
            row.append(float(np.mean(d[t - 3 : t])))
        return row + list(self.calendar[t])

    def fit_predict(self, end: int, horizon: int) -> np.ndarray:
        """Train on rows [0, end) and forecast rows [end, end + horizon) of z."""
        s = self.season
        z = self.z
        d = np.full(end + horizon, np.nan)
        d[s:end] = z[s:end] - z[: end - s]
        start = max(self.first, end - self.settings.max_training_rows)
        rows = np.arange(start, end)
        if len(rows) < 8:
            raise errors.too_short(min_rows(s, horizon, self.settings.folds), len(z))
        features = np.array([self._features(d, t) for t in rows])
        params = {
            "objective": "regression",
            "learning_rate": 0.05,
            "num_leaves": 15,
            "min_data_in_leaf": int(min(20, max(5, len(rows) // 20))),
            "seed": 0,
            "deterministic": True,
            "force_row_wise": True,
            "num_threads": os.cpu_count() or 1,
            "verbose": -1,
        }
        booster = lgb.train(params, lgb.Dataset(features, label=d[rows]), num_boost_round=300)
        z_hat = np.concatenate([z[:end], np.full(horizon, np.nan)])
        for t in range(end, end + horizon):
            d[t] = float(booster.predict(np.array([self._features(d, t)]))[0])
            z_hat[t] = z_hat[t - s] + d[t]
        return z_hat[end : end + horizon]


def _seasonal_naive(y: np.ndarray, end: int, horizon: int, season: int) -> np.ndarray:
    s = max(season, 1)
    return np.array([y[end - s + (j % s)] for j in range(horizon)])


def _scores(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    error = np.abs(actual - predicted)
    mape = None if np.any(actual == 0) else float(np.mean(error / np.abs(actual)) * 100)
    return {"mae": float(np.mean(error)), "mape": mape}


def _iso(stamp: pd.Timestamp, frequency: str) -> str:
    base = frequency.split("-")[0].lstrip("0123456789").upper()
    return stamp.isoformat() if base in {"H", "BH", "MIN", "T", "S"} else stamp.date().isoformat()


def run(series: Series, settings: Settings, horizon: int | None, dataset: dict[str, Any]) -> dict[str, Any]:
    season = series.season_length
    h = default_horizon(season) if horizon is None else horizon
    if h < 1:
        raise errors.bad_horizon("it must be a whole number of periods, 1 or more")
    if h > max_horizon(season):
        raise errors.bad_horizon(f"at most {max_horizon(season)} periods for this frequency")
    n = len(series.values)
    needed = min_rows(season, h, settings.folds)
    if n < needed:
        raise errors.too_short(needed, n)

    y = series.values
    use_log = bool(np.all(y > 0))
    z = np.log(y) if use_log else y.copy()
    future = pd.date_range(series.dates[-1], periods=h + 1, freq=series.frequency)[1:]
    calendar = _calendar(series.dates.append(future), series.frequency)
    model = _Model(z, calendar, season, settings)

    folds = []
    pooled = {"actual": [], "baseline": [], "model": []}
    for k in range(settings.folds):
        start = n - (settings.folds - k) * h
        actual = y[start : start + h]
        baseline = _seasonal_naive(y, start, h, season)
        z_hat = model.fit_predict(start, h)
        predicted = np.exp(z_hat) if use_log else z_hat
        folds.append(
            {
                "fold": k + 1,
                "train_start": _iso(series.dates[0], series.frequency),
                "train_end": _iso(series.dates[start - 1], series.frequency),
                "test_start": _iso(series.dates[start], series.frequency),
                "test_end": _iso(series.dates[start + h - 1], series.frequency),
                "baseline": _scores(actual, baseline),
                "model": _scores(actual, predicted),
            }
        )
        pooled["actual"].append(actual)
        pooled["baseline"].append(baseline)
        pooled["model"].append(predicted)

    actual = np.concatenate(pooled["actual"])
    baseline_all = np.concatenate(pooled["baseline"])
    model_all = np.concatenate(pooled["model"])
    overall = {"baseline": _scores(actual, baseline_all), "model": _scores(actual, model_all)}
    winner = "model" if overall["model"]["mae"] < overall["baseline"]["mae"] else "baseline"

    # Final forecast from all the data, with the interval from the backtest errors.
    final_z = model.fit_predict(n, h)
    if use_log:
        residuals = np.log(actual) - np.log(model_all)
        low, high = np.quantile(residuals, [(1 - INTERVAL) / 2, 1 - (1 - INTERVAL) / 2])
        point = np.exp(final_z)
        lower, upper = point * np.exp(low), point * np.exp(high)
    else:
        residuals = actual - model_all
        low, high = np.quantile(residuals, [(1 - INTERVAL) / 2, 1 - (1 - INTERVAL) / 2])
        point = final_z
        lower, upper = point + low, point + high
    baseline_future = _seasonal_naive(np.concatenate([y, np.zeros(h)]), n, h, season)

    history_start = max(0, n - HISTORY_POINTS)
    return {
        "schema": "tibyan-lab/forecast-check@1",
        "dataset": {
            **dataset,
            "date_column": series.date_column,
            "value_column": series.value_column,
            "frequency": series.frequency,
            "season_length": season,
            "rows": n,
            "start": _iso(series.dates[0], series.frequency),
            "end": _iso(series.dates[-1], series.frequency),
        },
        "horizon": h,
        "methods": {
            "baseline": {"id": "seasonal_naive", "name": "Seasonal naive"},
            "model": {"id": "lightgbm", "name": "LightGBM"},
        },
        "metrics": [
            {"id": "mae", "name": "MAE", "unit": None},
            {"id": "mape", "name": "MAPE", "unit": "percent"},
        ],
        "folds": folds,
        "overall": overall,
        "winner": winner,
        "winner_metric": "mae",
        "history": [
            {"date": _iso(series.dates[i], series.frequency), "value": float(y[i])}
            for i in range(history_start, n)
        ],
        "forecast": {
            "interval": INTERVAL,
            "points": [
                {
                    "date": _iso(future[j], series.frequency),
                    "model": float(point[j]),
                    "lower": float(lower[j]),
                    "upper": float(upper[j]),
                    "baseline": float(baseline_future[j]),
                }
                for j in range(h)
            ],
        },
    }
