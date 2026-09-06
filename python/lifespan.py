"""Lifespan composition helpers.

The backend's compatibility lifespan remains in ``app.py`` while services are
migrated.  These helpers keep container state attached to the ASGI app and
provide a stable boundary for the eventual full extraction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from runtime_container import RuntimeContainer


def bind_runtime_container(app: FastAPI, container: RuntimeContainer) -> RuntimeContainer:
    app.state.runtime = container
    return container


def with_runtime_container(
    handler: Callable[[FastAPI], Any],
    container: RuntimeContainer,
) -> Callable[[FastAPI], Any]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bind_runtime_container(app, container)
        async with handler(app):
            container.mark_started()
            try:
                yield
            finally:
                container.mark_stopped()

    return lifespan


__all__ = ["bind_runtime_container", "with_runtime_container"]
