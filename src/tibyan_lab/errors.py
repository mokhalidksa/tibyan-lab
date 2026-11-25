"""Errors with the codes defined in tibyan-web's docs/lab-api.md (Errors)."""

from __future__ import annotations

from typing import Any


class LabError(Exception):
    """A request the service refuses. The message is for API users and never quotes the upload."""

    def __init__(self, code: str, status: int, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.retry_after = retry_after


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"schema": "tibyan-lab/error@1", "error": {"code": code, "message": message}}


def file_missing() -> LabError:
    return LabError("file_missing", 400, "Send the CSV as a multipart form field named 'file'.")


def unsupported_type() -> LabError:
    return LabError(
        "unsupported_type", 415, "The file must be a CSV with a header row, in UTF-8 or Windows-1252."
    )


def too_large(limit: int) -> LabError:
    return LabError("too_large", 413, f"The file is larger than {limit // (1024 * 1024)} MB.")


def too_many_rows(limit: int) -> LabError:
    return LabError("too_many_rows", 422, f"The file has more than {limit:,} rows.")


def no_date_column() -> LabError:
    return LabError("no_date_column", 422, "No column could be read as dates.")


def no_value_column() -> LabError:
    return LabError("no_value_column", 422, "No column could be read as numbers.")


def irregular_dates(detail: str) -> LabError:
    return LabError("irregular_dates", 422, f"The dates do not follow a regular frequency: {detail}.")


def too_short(needed: int, found: int) -> LabError:
    return LabError(
        "too_short",
        422,
        f"The series needs at least {needed} rows for three backtest windows; it has {found}.",
    )


def bad_horizon(detail: str) -> LabError:
    return LabError("bad_horizon", 422, f"The horizon is not usable: {detail}.")


def rate_limited(retry_after: int) -> LabError:
    return LabError(
        "rate_limited", 429, "Too many requests from this address. Try again later.", retry_after=retry_after
    )


def timeout(seconds: float) -> LabError:
    return LabError("timeout", 504, f"The check took longer than {seconds:g} seconds.")


def unavailable() -> LabError:
    return LabError("unavailable", 503, "Document extraction is not switched on yet.")


def internal() -> LabError:
    return LabError("internal", 500, "Something went wrong on our side.")
