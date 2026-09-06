"""FastAPI application factory boundary."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI


def create_app(
    container: Any | None = None,
    *,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
    title: str = "yuizaki",
) -> FastAPI:
    """Create an application without importing provider or route modules."""
    app = FastAPI(title=title, lifespan=lifespan)
    if container is not None:
        app.state.runtime = container
    return app


__all__ = ["create_app"]
