"""Machine-readable HTTP route contract for the Electron control proxy."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute


DEFAULT_PROXY_PREFIXES = ("/api/", "/memory/", "/system/", "/health", "/v1/")


def build_route_manifest(
    app: FastAPI,
    *,
    proxy_prefixes: Iterable[str] = DEFAULT_PROXY_PREFIXES,
) -> dict[str, Any]:
    prefixes = tuple(proxy_prefixes)
    routes: list[dict[str, Any]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = str(route.path)
        if not path.startswith(prefixes):
            continue
        methods = sorted(str(method).upper() for method in (route.methods or set()))
        routes.append({
            "path": path,
            "methods": methods,
            "name": route.name,
            "proxy": True,
        })
    routes.sort(key=lambda item: (str(item["path"]), tuple(item["methods"])))
    return {
        "schema_version": 1,
        "proxy_prefixes": list(prefixes),
        "routes": routes,
    }


__all__ = ["DEFAULT_PROXY_PREFIXES", "build_route_manifest"]
