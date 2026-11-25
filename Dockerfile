# The tibyan-lab API. Listens on $PORT (default 8080); hosts that scale to zero set it.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8080

# LightGBM needs the OpenMP runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.10 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Run as an unprivileged user. The app writes nothing to disk.
RUN useradd --create-home --uid 10001 lab
USER lab
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080
# No access log: request lines carry client addresses, and nothing here needs them.
CMD ["sh", "-c", "exec uvicorn tibyan_lab.app:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
