# tibyan-lab

The API behind the lab demos on [tibyan.tech/lab](https://tibyan.tech/lab/).

## Forecast check

`POST /forecast-check` takes a CSV with one date column and one numeric column and answers one question: does a gradient-boosted model beat a simple seasonal baseline on this data, and by how much?

- Input: a `multipart/form-data` field `file` (CSV with a header row, at most 5 MB and 50,000 rows), and an optional `horizon` (whole number of periods; default one season).
- Output: JSON in the format `tibyan-lab/forecast-check@1`, defined in tibyan-web's `docs/lab-api.md`: errors per backtest window and overall for both methods, the winner, the recent history, and the final forecast with an 80% interval.
- Errors: JSON with a code (`too_large`, `too_many_rows`, `no_date_column`, `irregular_dates`, `too_short`, `bad_horizon`, `rate_limited`, `timeout` and others) and a plain message.

### How the backtest works

1. **Reading the file.** The first column that reads as dates and the first numeric column after it are used. Dates must be regular (pandas infers the frequency) and unique. The season length follows the frequency: 12 for monthly data, 7 for daily, 24 for hourly, 52 for weekly, 4 for quarterly.
2. **Folds.** A rolling-origin backtest with three folds. The last three windows of `horizon` periods are the test windows; each fold trains only on the data before its window.
3. **Baseline: seasonal naive.** Each forecast repeats the value from one season earlier.
4. **Model: LightGBM.** It learns the change from one season earlier, in log space when every value is positive, from the last three changes, the change one season ago, the average change over the last season, and calendar fields. Forecasts are recursive. Learning the change rather than the level lets the trees follow a trend. Training uses at most the latest 10,000 rows.
5. **Errors.** MAE, and MAPE in percent (left out for a window that contains a zero). The overall figures pool every test point. The method with the lower overall MAE wins; a tie goes to the baseline.
6. **Interval.** The 10th and 90th percentiles of the model's backtest errors, applied to the final forecast, give an 80% interval.

### Measured on the sample datasets

From `scripts/make_samples.py`, which runs exactly this code on the bundled datasets (25 November 2026):

| Dataset | Rows | Horizon | Baseline MAE | Model MAE | Baseline MAPE | Model MAPE | Winner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mauna Loa CO2, monthly (NOAA GML) | 824 | 12 months | 2.758 | 0.651 | 0.647% | 0.153% | Model |
| US births, daily (FiveThirtyEight, SSA data) | 5,479 | 7 days | 976.524 | 410.949 | 10.640% | 4.208% | Model |

CO2 is in parts per million; births are births per day. These are three test windows at the end of each series, so they say how the methods compare on those periods, not in general. The US births windows fall in December 2014 and include Christmas, where repeating last week does badly.

Timing: a 50,000-row hourly file took 0.85 seconds end to end on a development laptop. A host with a fraction of a CPU will be slower; the service stops any check at 20 seconds.

### Privacy and limits

- Uploads are read into memory and parsed there; nothing is written to disk. The request body is refused as soon as it passes 5 MB.
- Nothing from a file is logged. The container runs without an access log.
- Each IP address gets 10 checks per 10 minutes (`RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`). Behind a proxy, set `TRUSTED_PROXY_HOPS` to the number of proxies that append to `X-Forwarded-For` (default 1).
- CORS allows `https://tibyan.tech`. Add origins for testing with `ALLOWED_ORIGINS` (comma-separated).

## Document extraction (built, switched off)

`POST /extract` takes one invoice (PDF, PNG, JPEG or WebP; at most 5 MB and 3 pages) and returns `tibyan-lab/document-extraction@1`: vendor, invoice number, dates, currency, line items, subtotal, tax and total, each with the page and box or text it came from and a high or low confidence flag. A second step checks that the line amounts add up to the subtotal and flags them when they do not.

- The model sits behind one interface (`src/tibyan_lab/extract/provider.py`). Only a mock provider exists, used by the tests; with no provider configured the endpoint answers `503 unavailable`.
- Limits: 5 documents per IP address per day, 200 a day in all (`EXTRACT_DAILY_TOTAL`), plus the general rate limit. Refused files do not use the quota.
- `scripts/evaluate.py` measures field-level accuracy on a labelled set and writes `accuracy.json`. It has not been run: there is no provider or API key yet, so there are no accuracy numbers.

## Run it

```
uv sync
uv run uvicorn tibyan_lab.app:app --reload
uv run pytest
uv run ruff check .
```

Container:

```
docker build -t tibyan-lab .
docker run -p 8080:8080 tibyan-lab
```

Refresh the sample files for the site (writes `index.json` and one file per dataset):

```
uv run python scripts/make_samples.py --out ../tibyan-web/public/lab/samples/forecast-check
```

## Data

The bundled datasets and their licences are listed in `data/SOURCES.md`. `scripts/fetch_data.py` downloads them again.
