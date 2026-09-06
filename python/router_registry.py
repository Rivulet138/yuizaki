"""Small router registry used by the composition root during migration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, FastAPI


class RouterRegistry:
    def __init__(self, app: FastAPI):
        self.app = app
        self.registered: list[str] = []

    def include(self, router: APIRouter, *, name: str | None = None, **kwargs: Any) -> None:
        self.app.include_router(router, **kwargs)
        self.registered.append(name or getattr(router, "prefix", "router") or "router")

    def include_many(self, routers: Iterable[tuple[str, APIRouter]]) -> None:
        for name, router in routers:
            self.include(router, name=name)


__all__ = ["RouterRegistry"]
