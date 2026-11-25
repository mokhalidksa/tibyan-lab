from __future__ import annotations

import pytest

from tibyan_lab.errors import LabError
from tibyan_lab.settings import Settings
from tibyan_lab.validation import parse_series, season_for

from .conftest import monthly_csv, trending_seasonal


def code_of(raw: bytes, settings: Settings | None = None) -> str:
    with pytest.raises(LabError) as caught:
        parse_series(raw, settings or Settings())
    return caught.value.code


def test_monthly_series_is_read_with_its_frequency() -> None:
    series = parse_series(monthly_csv(trending_seasonal(48)), Settings())
    assert series.frequency == "MS"
    assert series.season_length == 12
    assert series.date_column == "month"
    assert series.value_column == "value"
    assert len(series.values) == 48


def test_semicolons_and_a_byte_order_mark_are_accepted() -> None:
    raw = "﻿date;sales\n2024-01-01;10\n2024-01-02;12\n2024-01-03;11\n2024-01-04;13\n".encode()
    series = parse_series(raw, Settings())
    assert series.frequency == "D"
    assert series.value_column == "sales"


def test_whole_years_count_as_dates() -> None:
    raw = b"year,value\n" + b"".join(f"{y},{y - 1900}\n".encode() for y in range(1950, 2000))
    series = parse_series(raw, Settings())
    assert series.season_length == 1
    assert series.dates[0].year == 1950


def test_rows_out_of_order_are_sorted() -> None:
    raw = b"d,v\n2024-03-01,3\n2024-01-01,1\n2024-02-01,2\n2024-04-01,4\n"
    series = parse_series(raw, Settings())
    assert list(series.values) == [1, 2, 3, 4]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"name,value\nalpha,1\nbeta,2\ngamma,3\n", "no_date_column"),
        (b"date,label\n2024-01-01,a\n2024-02-01,b\n2024-03-01,c\n", "no_value_column"),
        (b"date\n2024-01-01\n2024-02-01\n", "no_value_column"),
        (b"date,v\n2024-01-01,1\n2024-01-01,2\n2024-01-02,3\n", "irregular_dates"),
        (b"date,v\n2024-01-01,1\n2024-01-02,2\n2024-01-05,3\n2024-01-06,4\n", "irregular_dates"),
        (b"date,v\n2024-01-01,1\n2024-01-02,2\n", "too_short"),
        (b"\x81\x8d\x8f\x90\x9d,\x81\n", "unsupported_type"),
    ],
)
def test_bad_files_are_refused_with_a_code(raw: bytes, code: str) -> None:
    assert code_of(raw) == code


def test_too_many_rows() -> None:
    assert code_of(monthly_csv(trending_seasonal(60)), Settings(max_rows=50)) == "too_many_rows"


@pytest.mark.parametrize(
    ("frequency", "season"),
    [("MS", 12), ("ME", 12), ("D", 7), ("B", 5), ("W-SUN", 52), ("h", 24), ("QS-OCT", 4), ("YS-JAN", 1)],
)
def test_season_lengths(frequency: str, season: int) -> None:
    assert season_for(frequency) == season
