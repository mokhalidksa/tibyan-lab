from __future__ import annotations

import builtins
import logging
import os
import tempfile
import time

import pytest

from tibyan_lab import backtest
from tibyan_lab.settings import Settings

from .conftest import DATA, monthly_csv, trending_seasonal


def post_csv(client, raw: bytes, name: str = "series.csv", **data):
    return client.post("/forecast-check", files={"file": (name, raw, "text/csv")}, data=data)


def test_end_to_end_backtest_on_a_bundled_public_dataset(client) -> None:
    response = post_csv(client, (DATA / "co2_monthly.csv").read_bytes(), "co2_monthly.csv")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "tibyan-lab/forecast-check@1"
    assert body["dataset"]["id"] == "upload" and body["dataset"]["name"] == "co2_monthly.csv"
    assert body["dataset"]["frequency"] == "MS" and body["horizon"] == 12
    assert len(body["folds"]) == 3 and len(body["forecast"]["points"]) == 12
    assert body["winner"] in {"model", "baseline"}


def test_horizon_is_read_from_the_form(client) -> None:
    response = post_csv(client, monthly_csv(trending_seasonal(120)), horizon="6")
    assert response.status_code == 200
    assert response.json()["horizon"] == 6


@pytest.mark.parametrize("horizon", ["0", "-3", "six", "1.5"])
def test_bad_horizon(client, horizon: str) -> None:
    response = post_csv(client, monthly_csv(trending_seasonal(120)), horizon=horizon)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "bad_horizon"


def test_missing_file(client) -> None:
    response = client.post("/forecast-check", data={"horizon": "3"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file_missing"


def test_not_a_form(client) -> None:
    response = client.post("/forecast-check", json={"file": "x"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file_missing"


def test_too_large_is_refused_before_reading(client) -> None:
    big = b"date,value\n" + b"2024-01-01,1\n" * 500_000
    response = post_csv(client, big)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"


def test_rate_limit(make_client) -> None:
    client = make_client(Settings(rate_limit_requests=2))
    raw = monthly_csv(trending_seasonal(120))
    assert post_csv(client, raw).status_code == 200
    assert post_csv(client, raw).status_code == 200
    third = post_csv(client, raw)
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
    assert int(third.headers["retry-after"]) > 0


def test_cors_allows_only_the_site(client) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    allowed = client.options("/forecast-check", headers={"Origin": "https://tibyan.tech", **preflight})
    assert allowed.headers.get("access-control-allow-origin") == "https://tibyan.tech"
    other = client.options("/forecast-check", headers={"Origin": "https://example.com", **preflight})
    assert "access-control-allow-origin" not in other.headers


def test_timeout(make_client, monkeypatch) -> None:
    client = make_client(Settings(rate_limit_requests=1000, timeout_seconds=0.2))
    real_run = backtest.run

    def slow(*args, **kwargs):
        time.sleep(1)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(backtest, "run", slow)
    response = post_csv(client, monthly_csv(trending_seasonal(120)))
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


def test_upload_never_touches_the_disk(client, monkeypatch) -> None:
    """A 2 MB upload (twice Starlette's spooling threshold) with every way of writing a file blocked."""

    def refuse(*args, **kwargs):
        raise AssertionError("an upload tried to write to disk")

    # Warm up first, so every module is already imported and no bytecode cache is written mid-test.
    assert post_csv(client, monthly_csv(trending_seasonal(120))).status_code == 200
    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"an upload tried to open {file!r} for writing")
        return real_open(file, mode, *args, **kwargs)

    for name in ("SpooledTemporaryFile", "TemporaryFile", "NamedTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, refuse)
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", refuse)

    values = trending_seasonal(48)
    rows = "".join(f"2015-{m:02d}-01,{v},{'x' * 1000}\n" for m, v in zip(range(1, 13), values, strict=False))
    padding = "".join(f"2016-{(i % 12) + 1:02d}-01,{v},{'y' * 1000}\n" for i, v in enumerate(values))
    raw = ("month,value,notes\n" + rows + padding).encode()
    raw = raw + b"\n" * (2 * 1024 * 1024 - len(raw))
    response = post_csv(client, raw)
    assert response.status_code in {200, 422}


def test_file_contents_never_reach_the_logs(client, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "PRIVATE_MARKER_7731"
    raw = f"date,{marker}\n2024-01-01,1\n2024-01-01,2\n".encode()
    response = post_csv(client, raw)
    assert response.status_code == 422
    assert marker not in caplog.text
    assert marker not in response.text
