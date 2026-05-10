"""Error envelope middleware for /v1/* routes.

Maps known orchestration error types to the design §4 error envelope:
`{"error": {"code", "message", "details"}}`. Unknown errors become
`INTERNAL` with a generic message.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from soundings.orchestration.errors import (
    GeographyNotFoundError,
    IndicatorNotAvailableAtLevelError,
    IndicatorNotRegisteredError,
    OrchestrationError,
)

CODE_TO_STATUS: dict[str, int] = {
    "GEOGRAPHY_NOT_FOUND": 404,
    "INDICATOR_NOT_AVAILABLE_AT_LEVEL": 422,
    "INDICATOR_NOT_REGISTERED": 404,
    "UPSTREAM_TIMEOUT": 504,
    "RATE_LIMITED": 429,
    "INTERNAL": 500,
}


def _envelope(code: str, message: str, details: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=CODE_TO_STATUS.get(code, 500),
        content={"error": {"code": code, "message": message, "details": details}},
    )


async def _orchestration_handler(request: Request, exc: OrchestrationError) -> JSONResponse:
    details: dict[str, Any] = {}
    if isinstance(exc, GeographyNotFoundError):
        details = {"place_id": exc.place_id}
    elif isinstance(exc, IndicatorNotAvailableAtLevelError):
        details = {
            "indicator": exc.indicator_key,
            "place_id": exc.place_id,
            "available_at": exc.available_at,
        }
    elif isinstance(exc, IndicatorNotRegisteredError):
        details = {"indicator": exc.indicator_key}
    return _envelope(exc.code, str(exc), details)


async def _fallback_handler(request: Request, exc: Exception) -> JSONResponse:
    return _envelope(
        "INTERNAL",
        "Internal server error.",
        {"exception": exc.__class__.__name__},
    )


def install_error_envelope(app: FastAPI) -> None:
    app.add_exception_handler(OrchestrationError, _orchestration_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _fallback_handler)
