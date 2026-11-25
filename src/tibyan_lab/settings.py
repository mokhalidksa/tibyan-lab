"""Every limit the service enforces, in one place (CLAUDE.md, rule 3)."""

from __future__ import annotations

import os
from dataclasses import dataclass

PRODUCTION_ORIGIN = "https://tibyan.tech"


@dataclass(frozen=True)
class Settings:
    #: Largest accepted upload, in bytes.
    max_upload_bytes: int = 5 * 1024 * 1024
    #: Largest accepted CSV, in data rows.
    max_rows: int = 50_000
    #: Wall-clock limit for parsing and backtesting one upload.
    timeout_seconds: float = 20.0
    #: Requests allowed per client IP within the window.
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 600
    #: Origins allowed by CORS. The first is always the production site.
    allowed_origins: tuple[str, ...] = (PRODUCTION_ORIGIN,)
    #: Proxies in front of the service that append to X-Forwarded-For.
    trusted_proxy_hops: int = 1
    #: The model trains on at most this many of the latest rows, to stay inside the time limit.
    max_training_rows: int = 10_000
    #: Rolling-origin folds in the backtest.
    folds: int = 3
    #: Document extraction: pages per document, documents per IP per day, documents per day in all.
    max_pages: int = 3
    extract_daily_per_ip: int = 5
    extract_daily_total: int = 200
    #: Which model provider reads invoices. Empty keeps /extract switched off.
    extract_provider: str = ""


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def load_settings() -> Settings:
    """Settings from the environment. Only the limits that differ between hosts are configurable."""
    extra = tuple(
        origin.strip() for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",") if origin.strip()
    )
    return Settings(
        allowed_origins=(PRODUCTION_ORIGIN, *extra),
        trusted_proxy_hops=_int("TRUSTED_PROXY_HOPS", 1),
        rate_limit_requests=_int("RATE_LIMIT_REQUESTS", 10),
        rate_limit_window_seconds=_int("RATE_LIMIT_WINDOW_SECONDS", 600),
        extract_daily_total=_int("EXTRACT_DAILY_TOTAL", 200),
        extract_provider=os.environ.get("EXTRACT_PROVIDER", ""),
    )
