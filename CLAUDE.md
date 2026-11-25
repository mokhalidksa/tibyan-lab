# tibyan-lab

The API behind the lab demos on https://tibyan.tech/lab/. Public repository.
Stack: Python, FastAPI, uv, pytest, ruff, Docker.

The response formats are defined in tibyan-web's `docs/lab-api.md`. That file is the contract; change it there first.

## Commands

- `uv sync` installs everything, including dev tools.
- `uv run uvicorn tibyan_lab.app:app --reload` runs the API locally.
- `uv run pytest` runs the tests.
- `uv run ruff check . && uv run ruff format --check .` lints.
- `uv run python scripts/make_samples.py --out <tibyan-web>/public/lab/samples/forecast-check` writes the site's sample files.
- Before every commit run: `uv run ruff check . && uv run pytest`.

## Hard rules

1. Uploads are handled in memory only. No uploaded file, or any part of one, is written to disk.
2. No file content is ever logged: not in access logs, error logs or exception messages. Log request metadata only (path, status, duration).
3. Every limit lives in `src/tibyan_lab/settings.py` and is enforced before work starts: 5 MB, 50,000 rows, 20 seconds, per-IP rate limit.
4. CORS allows https://tibyan.tech only (plus origins added through the `ALLOWED_ORIGINS` environment variable for local testing).
5. API keys and secrets come from the environment only. Nothing secret is committed.
6. Error responses use the codes in docs/lab-api.md. Messages are plain and never quote the uploaded file.
7. Do not publish a number in the README or the samples that a script in this repo did not produce.

## Layout

```
src/tibyan_lab/   app.py (routes, limits), settings.py, validation.py, backtest.py, ratelimit.py, errors.py
data/             bundled public datasets, each with its source and licence in data/SOURCES.md
scripts/          make_samples.py (site sample files), fetch_data.py (refreshes data/)
tests/            pytest, including one end-to-end backtest on a bundled dataset
Dockerfile        the container that runs in production
```
