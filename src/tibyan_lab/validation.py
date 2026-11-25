"""Turning an uploaded CSV into a regular time series, or refusing it with a clear code."""

from __future__ import annotations

import csv
import io
import re
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import errors
from .settings import Settings

#: Share of a column's cells that must parse for it to count as dates or numbers.
PARSE_SHARE = 0.95


@dataclass
class Series:
    dates: pd.DatetimeIndex
    values: np.ndarray
    date_column: str
    value_column: str
    frequency: str
    season_length: int


def season_for(frequency: str) -> int:
    """Season length for a pandas frequency alias: the cycle a seasonal-naive forecast repeats."""
    base = re.sub(r"^\d+", "", frequency).split("-")[0].upper()
    if base in {"H", "BH"}:
        return 24
    if base in {"MIN", "T"}:
        return 60
    if base in {"S"}:
        return 60
    if base == "B":
        return 5
    if base in {"D", "C"}:
        return 7
    if base == "W":
        return 52
    if base in {"M", "MS", "ME", "BM", "BMS", "BME", "SM", "SMS"}:
        return 12
    if base in {"Q", "QS", "QE", "BQ", "BQS", "BQE"}:
        return 4
    return 1


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise errors.unsupported_type()


def _read_table(text: str) -> pd.DataFrame:
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    try:
        table = pd.read_csv(io.StringIO(text), sep=delimiter, skipinitialspace=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as error:
        raise errors.unsupported_type() from error
    table.columns = [str(column).strip() for column in table.columns]
    return table


def _as_dates(column: pd.Series) -> pd.Series | None:
    """The column as datetimes, or None if it does not read as dates."""
    if pd.api.types.is_numeric_dtype(column):
        numbers = pd.to_numeric(column, errors="coerce")
        whole = numbers.dropna()
        # Whole years such as 1949, 1950 read as dates; other numbers do not.
        if len(whole) and (whole % 1 == 0).all() and whole.between(1000, 3000).all():
            return pd.to_datetime(numbers.astype("Int64").astype("string") + "-01-01", errors="coerce")
        return None
    with warnings.catch_warnings():
        # Columns that are not dates make pandas warn while it gives up on them.
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(column.astype("string").str.strip(), errors="coerce")
    return parsed if parsed.notna().mean() >= PARSE_SHARE else None


def _as_numbers(column: pd.Series) -> pd.Series | None:
    if pd.api.types.is_numeric_dtype(column):
        numbers = pd.to_numeric(column, errors="coerce")
    else:
        cleaned = column.astype("string").str.strip().str.replace(",", "", regex=False)
        numbers = pd.to_numeric(cleaned, errors="coerce")
    return numbers if numbers.notna().mean() >= PARSE_SHARE else None


def _frequency(index: pd.DatetimeIndex) -> str | None:
    """The pandas frequency alias of a regular index, such as "MS" or "D", or None."""
    try:
        with pd.option_context("future.infer_freq_returns_offset", True):
            offset = pd.infer_freq(index)
    except (KeyError, pd.errors.OptionError):  # pandas without the option returns a string already
        offset = pd.infer_freq(index)
    if offset is None:
        return None
    return offset if isinstance(offset, str) else offset.freqstr


def parse_series(raw: bytes, settings: Settings) -> Series:
    """The first date column and the first numeric column after it, as a regular series."""
    text = _decode(raw)
    if text.count("\n") > settings.max_rows + 1:
        raise errors.too_many_rows(settings.max_rows)
    table = _read_table(text)
    if len(table) > settings.max_rows:
        raise errors.too_many_rows(settings.max_rows)
    if table.shape[1] < 2 or len(table) == 0:
        raise errors.no_value_column() if table.shape[1] >= 1 else errors.unsupported_type()

    date_name, dates = None, None
    for name in table.columns:
        parsed = _as_dates(table[name])
        if parsed is not None:
            date_name, dates = name, parsed
            break
    if dates is None or date_name is None:
        raise errors.no_date_column()

    value_name, values = None, None
    for name in table.columns:
        if name == date_name:
            continue
        numbers = _as_numbers(table[name])
        if numbers is not None:
            value_name, values = name, numbers
            break
    if values is None or value_name is None:
        raise errors.no_value_column()

    frame = pd.DataFrame({"date": dates, "value": values}).dropna()
    if frame["date"].duplicated().any():
        raise errors.irregular_dates("some dates appear more than once")
    frame = frame.sort_values("date")
    index = pd.DatetimeIndex(frame["date"])
    if len(index) < 3:
        raise errors.too_short(3, len(index))
    frequency = _frequency(index)
    if frequency is None:
        raise errors.irregular_dates("the gaps between dates are not all the same")

    return Series(
        dates=index,
        values=frame["value"].to_numpy(dtype=float),
        date_column=date_name,
        value_column=value_name,
        frequency=frequency,
        season_length=season_for(frequency),
    )
