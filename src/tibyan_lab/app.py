"""The lab API. One public endpoint for now: POST /forecast-check.

Limits are checked in this order, before any work: rate limit, upload size, row count,
then a 20-second limit on parsing and backtesting together. Nothing from an upload is
written to disk or logged; the response is the only place its contents go.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, backtest, errors, uploads, validation
from .ratelimit import RateLimiter, client_ip
from .settings import Settings, load_settings

logger = logging.getLogger("tibyan_lab")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    limiter = RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
    app = FastAPI(title="tibyan-lab", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.limiter = limiter
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )

    @app.exception_handler(errors.LabError)
    async def lab_error(_: Request, error: errors.LabError) -> JSONResponse:
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return JSONResponse(
            errors.error_body(error.code, error.message), status_code=error.status, headers=headers
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        # Log the type only: an exception message could quote the upload.
        logger.error("unexpected error: %s", type(error).__name__)
        failure = errors.internal()
        return JSONResponse(errors.error_body(failure.code, failure.message), status_code=failure.status)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/forecast-check")
    async def forecast_check(request: Request) -> dict[str, Any]:
        peer = request.client.host if request.client else None
        wait = limiter.check(
            client_ip(request.headers.get("x-forwarded-for"), peer, settings.trusted_proxy_hops)
        )
        if wait is not None:
            raise errors.rate_limited(wait)

        body = await uploads.read_body(
            request.stream(), request.headers.get("content-length"), settings.max_upload_bytes
        )
        form = uploads.parse_form(body, request.headers.get("content-type"))
        upload = form.get("file")
        if upload is None or not upload.data:
            raise errors.file_missing()
        if len(upload.data) > settings.max_upload_bytes:
            raise errors.too_large(settings.max_upload_bytes)
        horizon_part = form.get("horizon")
        horizon = _horizon(horizon_part.data if horizon_part else None)

        def work() -> dict[str, Any]:
            series = validation.parse_series(upload.data, settings)
            return backtest.run(
                series, settings, horizon, {"id": "upload", "name": upload.filename or "upload"}
            )

        try:
            return await asyncio.wait_for(asyncio.to_thread(work), timeout=settings.timeout_seconds)
        except TimeoutError as error:
            raise errors.timeout(settings.timeout_seconds) from error

    return app


def _horizon(raw: bytes | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    text = raw.decode("utf-8", "replace").strip()
    if not text.isdigit():
        raise errors.bad_horizon("it must be a whole number of periods, 1 or more")
    return int(text)


app = create_app()
