from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tibyan_lab.app import create_app
from tibyan_lab.settings import Settings

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def settings() -> Settings:
    return Settings(rate_limit_requests=1000)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def make_client() -> Callable[[Settings], TestClient]:
    return lambda settings: TestClient(create_app(settings))


def monthly_csv(values: np.ndarray, start: str = "2015-01-01", header: str = "month,value") -> bytes:
    dates = pd.date_range(start, periods=len(values), freq="MS")
    lines = [header, *(f"{d.date().isoformat()},{v}" for d, v in zip(dates, values, strict=True))]
    return ("\n".join(lines) + "\n").encode()


def trending_seasonal(n: int = 120, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return np.round(200 + 1.5 * t + 30 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 3, n), 2)
