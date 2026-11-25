"""Refreshes the bundled public datasets in data/.

Each source is downloaded, reduced to a two-column CSV (date, value) and written to
data/ with its SHA-256 printed, so data/SOURCES.md can record exactly what was used.

    uv run python scripts/fetch_data.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

SOURCES = {
    "co2_monthly.csv": "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.csv",
    "us_births_daily.csv": "https://raw.githubusercontent.com/fivethirtyeight/data/master/births/US_births_2000-2014_SSA.csv",
}


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "tibyan-lab-data-fetch"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def co2(text: str) -> list[tuple[str, str]]:
    """NOAA GML Mauna Loa monthly mean CO2 (ppm). Rows with no measurement (-99.99) are dropped."""
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    rows = []
    for record in csv.DictReader(io.StringIO("\n".join(lines))):
        average = float(record["average"])
        if average < 0:
            continue
        rows.append((f"{int(record['year']):04d}-{int(record['month']):02d}-01", f"{average:.2f}"))
    return rows


def births(text: str) -> list[tuple[str, str]]:
    """US births per day, 2000 to 2014 (Social Security Administration, via FiveThirtyEight)."""
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        date = f"{int(record['year']):04d}-{int(record['month']):02d}-{int(record['date_of_month']):02d}"
        rows.append((date, record["births"]))
    return rows


def main() -> None:
    DATA.mkdir(exist_ok=True)
    converters = {
        "co2_monthly.csv": (co2, ("month", "co2_ppm")),
        "us_births_daily.csv": (births, ("date", "births")),
    }
    for name, url in SOURCES.items():
        convert, header = converters[name]
        rows = convert(fetch(url))
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        content = buffer.getvalue().encode("utf-8")
        (DATA / name).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        print(f"{name}: {len(rows)} rows, {rows[0][0]} to {rows[-1][0]}, sha256 {digest}")


if __name__ == "__main__":
    main()
