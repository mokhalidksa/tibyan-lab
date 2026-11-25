"""Field-level accuracy of the extractor on a labelled invoice set.

Writes tibyan-lab/extraction-eval@1 (tibyan-web docs/lab-api.md) to --out. Run it only
with a real provider configured; the numbers it writes are the only accuracy figures
the site may show, and only after they are added to tibyan-web's claims.ts.

    uv run python scripts/evaluate.py --data eval/ --out accuracy.json

--data holds one folder per invoice: the document (invoice.pdf, .png, .jpg or .webp)
and labels.json, an object of field ID to the correct value. Values compare after the
same normalisation the pipeline applies (dates ISO, money to two decimals, currency
upper case); a field counts as correct only on an exact match.

Not run yet: no provider or API key exists for this project.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from tibyan_lab.extract.pipeline import FIELD_NAMES, FIELD_TYPES, normalise, run
from tibyan_lab.extract.provider import FIELD_IDS, Provider
from tibyan_lab.settings import Settings


def load_provider(name: str) -> Provider:
    raise SystemExit(f"No provider called {name!r} exists yet. Add one under src/tibyan_lab/extract/ first.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-url", default="")
    parser.add_argument("--dataset-licence", default="")
    args = parser.parse_args()

    provider = load_provider(args.provider)
    settings = Settings()
    correct = dict.fromkeys(FIELD_IDS, 0)
    total = dict.fromkeys(FIELD_IDS, 0)
    documents = 0
    model = ""
    for folder in sorted(path for path in args.data.iterdir() if path.is_dir()):
        labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
        document = next(
            p for p in folder.iterdir() if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
        )
        result = run(document.read_bytes(), provider, settings, folder.name)
        model = result["model"]["name"]
        documents += 1
        got = {field["id"]: field["value"] for field in result["fields"]}
        for field_id in FIELD_IDS:
            if field_id not in labels:
                continue
            total[field_id] += 1
            expected, _ = normalise(FIELD_TYPES[field_id], labels[field_id])
            correct[field_id] += int(got[field_id] == expected)

    report = {
        "schema": "tibyan-lab/extraction-eval@1",
        "dataset": {
            "name": args.dataset_name,
            "url": args.dataset_url,
            "licence": args.dataset_licence,
            "documents": documents,
        },
        "model": {"provider": args.provider, "name": model},
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fields": [
            {"id": f, "name": FIELD_NAMES[f], "correct": correct[f], "total": total[f]}
            for f in FIELD_IDS
            if total[f]
        ],
        "overall": {"correct": sum(correct.values()), "total": sum(total.values())},
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    overall = report["overall"]
    print(f"evaluate: {documents} documents, {overall['correct']}/{overall['total']} fields correct")


if __name__ == "__main__":
    main()
