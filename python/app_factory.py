"""FastAPI application factory boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from modules.system.api_response import error_response
from starlette.exceptions import HTTPException as StarletteHTTPException


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Keep locations and messages while dropping input/context values."""
    safe: list[dict[str, Any]] = []
    for item in exc.errors():
        loc = [part if isinstance(part, (str, int)) else str(part) for part in item.get("loc", ())]
        safe.append(
            {
                "loc": loc,
                "type": str(item.get("type", "validation_error")),
                "msg": str(item.get("msg", "Invalid request")),
            }
        )
    return safe


def _install_exception_handlers(app: FastAPI) -> None:
    def detail_message(detail: Any, fallback: str) -> str:
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, list):
            messages = [
                str(item.get("msg"))
                for item in detail
                if isinstance(item, Mapping) and item.get("msg")
            ]
            if messages:
                return "; ".join(messages)[:2000]
        if isinstance(detail, Mapping):
            candidate = detail.get("message") or detail.get("detail")
            if candidate:
                return str(candidate)
        return fallback

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        detail_map = detail if isinstance(detail, Mapping) else {}
        code = str(detail_map.get("code") or detail_map.get("error") or f"http_{exc.status_code}")
        message = detail_message(detail_map.get("message") or detail, code)
        details = detail_map.get("details")
        if not isinstance(details, dict):
            details = None
        return error_response(
            code=code,
            message=message,
            status_code=exc.status_code,
            details=details,
            request_id=getattr(request.state, "trace_id", None),
            headers=exc.headers,
            legacy_detail=detail,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        safe_errors = _safe_validation_errors(exc)
        return error_response(
            code="validation_error",
            message="Request validation failed",
            status_code=422,
            details={"errors": safe_errors},
            request_id=getattr(request.state, "trace_id", None),
            legacy_detail=safe_errors,
        )


def create_app(
    container: Any | None = None,
    *,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    title: str = "yuizaki",
) -> FastAPI:
    """Create an application without importing provider or route modules."""
    app = FastAPI(title=title, lifespan=lifespan)
    _install_exception_handlers(app)
    if container is not None:
        app.state.runtime = container
    return app


__all__ = ["create_app"]
