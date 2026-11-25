"""Writes the forecast check sample files for tibyan-web, in the format of docs/lab-api.md.

Runs the same validation and backtest as the API on each bundled dataset, then writes
`index.json` and one `<id>.json` per sample into the output folder.

    uv run python scripts/make_samples.py --out ../web_tb_1/public/lab/samples/forecast-check
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from tibyan_lab import __version__, backtest, validation
from tibyan_lab.settings import Settings

ROOT = Path(__file__).resolve().parent.parent

SAMPLES = [
    {
        "id": "mauna-loa-co2",
        "name": "Mauna Loa CO2, monthly",
        "file": "co2_monthly.csv",
        "source": {
            "name": "NOAA Global Monitoring Laboratory",
            "url": "https://gml.noaa.gov/ccgg/trends/",
            "licence": "Free to use with credit to NOAA GML",
        },
    },
    {
        "id": "us-births",
        "name": "US births, daily",
        "file": "us_births_daily.csv",
        "source": {
            "name": "FiveThirtyEight, from Social Security Administration data",
            "url": "https://github.com/fivethirtyeight/data/tree/master/births",
            "licence": "CC BY 4.0",
        },
    },
]


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True, help="folder to write index.json and the sample files into"
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    settings = Settings()

    written = []
    for sample in SAMPLES:
        series = validation.parse_series((ROOT / "data" / sample["file"]).read_bytes(), settings)
        result = backtest.run(
            series, settings, None, {"id": sample["id"], "name": sample["name"], "source": sample["source"]}
        )
        path = args.out / f"{sample['id']}.json"
        path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
        written.append({"id": sample["id"], "name": sample["name"], "file": path.name})
        base, model = result["overall"]["baseline"], result["overall"]["model"]
        print(
            f"{sample['id']}: winner {result['winner']}; "
            f"MAE baseline {base['mae']:.3f}, model {model['mae']:.3f}; "
            f"MAPE baseline {base['mape']:.3f}, model {model['mape']:.3f}"
        )

    manifest = {
        "schema": "tibyan-lab/samples@1",
        "demo": "forecast-check",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generator": {"repo": "tibyan-lab", "version": __version__, "commit": commit()},
        "samples": written,
    }
    (args.out / "index.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {len(written)} samples and index.json to {args.out}")


if __name__ == "__main__":
    main()
