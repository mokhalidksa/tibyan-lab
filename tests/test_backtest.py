from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from tibyan_lab import backtest
from tibyan_lab.errors import LabError
from tibyan_lab.settings import Settings
from tibyan_lab.validation import parse_series

from .conftest import monthly_csv, trending_seasonal


def run(values: np.ndarray, horizon: int | None = None) -> dict:
    series = parse_series(monthly_csv(values), Settings())
    return backtest.run(series, Settings(), horizon, {"id": "test", "name": "test"})


def test_three_rolling_origin_folds_that_end_at_the_last_row() -> None:
    result = run(trending_seasonal(120))
    folds = result["folds"]
    assert [f["fold"] for f in folds] == [1, 2, 3]
    assert folds[-1]["test_end"] == result["dataset"]["end"]
    for earlier, later in itertools.pairwise(folds):
        assert earlier["test_end"] < later["test_start"]
    for fold in folds:
        assert fold["train_end"] < fold["test_start"]
        months = pd.Timestamp(fold["test_end"]).to_period("M") - pd.Timestamp(fold["test_start"]).to_period(
            "M"
        )
        assert months.n == result["horizon"] - 1


def test_the_model_beats_seasonal_naive_on_a_trending_series() -> None:
    result = run(trending_seasonal(120))
    assert result["winner"] == "model"
    assert result["overall"]["model"]["mae"] < result["overall"]["baseline"]["mae"]


def test_a_tie_goes_to_the_baseline() -> None:
    result = run(np.full(80, 50.0))
    assert result["overall"]["baseline"]["mae"] == 0
    assert result["winner"] == "baseline"


def test_mape_is_null_when_a_window_contains_zero() -> None:
    values = np.tile(np.array([0.0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1]), 10)
    result = run(values)
    assert all(fold["baseline"]["mape"] is None for fold in result["folds"])
    assert result["overall"]["model"]["mape"] is None


def test_forecast_shape_and_interval() -> None:
    result = run(trending_seasonal(120), horizon=6)
    points = result["forecast"]["points"]
    assert result["horizon"] == 6 and len(points) == 6
    assert result["forecast"]["interval"] == 0.8
    assert all(p["lower"] <= p["upper"] for p in points)
    assert points[0]["date"] > result["dataset"]["end"]


def test_history_is_capped() -> None:
    result = run(trending_seasonal(700))
    assert len(result["history"]) == backtest.HISTORY_POINTS
    assert result["history"][-1]["date"] == result["dataset"]["end"]


@pytest.mark.parametrize(
    ("values", "horizon", "code"),
    [(trending_seasonal(30), None, "too_short"), (trending_seasonal(120), 40, "bad_horizon")],
)
def test_refusals(values: np.ndarray, horizon: int | None, code: str) -> None:
    with pytest.raises(LabError) as caught:
        run(values, horizon)
    assert caught.value.code == code


def test_no_training_row_is_after_its_test_window() -> None:
    """Changing every value after a fold's training end must not change that fold's forecast."""
    values = trending_seasonal(120)
    calendar = np.zeros((132, 0))
    end, horizon = 84, 12
    original = backtest._Model(np.log(values), calendar, 12, Settings()).fit_predict(end, horizon)
    changed = values.copy()
    changed[end:] *= 50
    altered = backtest._Model(np.log(changed), calendar, 12, Settings()).fit_predict(end, horizon)
    np.testing.assert_allclose(original, altered)
