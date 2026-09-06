"""HTTP observability primitives shared by the application factory.

The middleware intentionally records only route metadata and elapsed time. It
does not retain request bodies, query strings, authorization headers, or user
content. This keeps the signal useful for latency work without expanding the
privacy boundary of the local-first runtime.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from modules.system.backend_api_auth import (
    HOST_DESKTOP_ACTION_PREFIX,
    HOST_DESKTOP_ACTION_TOKEN_ENV,
    backend_api_auth_required,
    verify_backend_api_authorization,
    verify_host_desktop_action_authorization,
)


def install_request_timing_middleware(app: Any, logger: logging.Logger) -> None:
    """Install bounded request timing headers and structured log fields."""

    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next: Callable[..., Any]) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.exception(
                "[trace:%s] %s %s failed duration_ms=%s",
                getattr(request.state, "trace_id", ""),
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise

        elapsed_ms = round(max(0.0, (time.perf_counter() - started) * 1000), 1)
        request.state.duration_ms = elapsed_ms
        response.headers["x-request-duration-ms"] = str(elapsed_ms)
        response.headers["server-timing"] = f"app;dur={elapsed_ms}"
        logger.info(
            "[trace:%s] %s %s status=%s duration_ms=%s",
            getattr(request.state, "trace_id", ""),
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


def install_backend_http_middleware(
    app: Any,
    *,
    logger: logging.Logger,
    backend_api_token: str,
) -> None:
    """Install auth, trace and timing middleware as one app boundary."""

    @app.middleware("http")
    async def backend_api_auth_middleware(request: Request, call_next: Callable[..., Any]) -> Response:
        if request.url.path in {"/api/ping", "/api/system/ui-capabilities"}:
            return await call_next(request)
        if request.url.path == HOST_DESKTOP_ACTION_PREFIX or request.url.path.startswith(
            f"{HOST_DESKTOP_ACTION_PREFIX}/"
        ):
            allowed, message = verify_host_desktop_action_authorization(
                request.headers.get("authorization"),
                os.getenv(HOST_DESKTOP_ACTION_TOKEN_ENV, ""),
                backend_api_token,
            )
            if not allowed:
                return JSONResponse({"error": "unauthorized", "message": message}, status_code=401)
            return await call_next(request)
        client_host = request.client.host if request.client else None
        if backend_api_auth_required(request.url.path, request.method, client_host=client_host):
            allowed, message = verify_backend_api_authorization(
                request.headers.get("authorization"),
                backend_api_token,
                request.headers.get("x-yuizaki-backend-token"),
                client_host=client_host,
            )
            if not allowed:
                return JSONResponse({"error": "unauthorized", "message": message}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next: Callable[..., Any]) -> Response:
        trace_id = request.headers.get("x-trace-id") or f"trace_{uuid.uuid4().hex[:12]}"
        request.state.trace_id = trace_id
        logger.info("[trace:%s] %s %s", trace_id, request.method, request.url.path)
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response

    install_request_timing_middleware(app, logger)


__all__ = ["install_backend_http_middleware", "install_request_timing_middleware"]
