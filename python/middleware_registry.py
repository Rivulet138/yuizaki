"""Central registration point for HTTP middleware."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modules.system.http_observability import install_backend_http_middleware


def register_http_middleware(
    app: FastAPI,
    *,
    logger: logging.Logger,
    backend_api_token: str,
    allowed_origins: Iterable[str],
) -> None:
    install_backend_http_middleware(app, logger=logger, backend_api_token=backend_api_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "x-trace-id", "x-yuizaki-backend-token"],
    )


__all__ = ["register_http_middleware"]
