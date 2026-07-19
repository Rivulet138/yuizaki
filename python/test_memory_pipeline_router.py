from __future__ import annotations

from typing import Any, Callable, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient


_create_memory_pipeline_router = cast(
    Callable[..., Any],
    __import__("modules.memory.routes", fromlist=["create_memory_pipeline_router"]).create_memory_pipeline_router,
)


def test_memory_pipeline_router_exposes_query_route_and_forwards_params() -> None:
    app = FastAPI()
    captured: dict[str, object] = {}

    def _handler(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "query": kwargs.get("query"), "top_k": kwargs.get("top_k")}

    app.include_router(_create_memory_pipeline_router(_handler))
    client = TestClient(app)

    response = client.get(
        "/api/memory/pipeline/query",
        params={
            "query": "总结一下",
            "session_id": "sess-1",
            "workspace_id": "ws-1",
            "scope": "workspace",
            "layers": "relationship,reflective",
            "top_k": 9,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "query": "总结一下", "top_k": 9}
    assert captured == {
        "query": "总结一下",
        "session_id": "sess-1",
        "workspace_id": "ws-1",
        "scope": "workspace",
        "layers": "relationship,reflective",
        "top_k": 9,
    }


def test_memory_pipeline_router_rejects_cross_workspace_query() -> None:
    app = FastAPI()

    def _handler(**kwargs: object) -> dict[str, object]:
        return {"ok": True, "workspace_id": kwargs.get("workspace_id")}

    app.include_router(_create_memory_pipeline_router(_handler, get_active_workspace_id=lambda: "ws-active"))
    client = TestClient(app)

    response = client.get(
        "/api/memory/pipeline/query",
        params={"query": "hello", "workspace_id": "ws-other", "scope": "workspace"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "workspace_mismatch"


def test_memory_pipeline_router_defaults_workspace_query_to_active_workspace() -> None:
    app = FastAPI()
    captured: dict[str, object] = {}

    def _handler(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "workspace_id": kwargs.get("workspace_id"), "scope": kwargs.get("scope")}

    app.include_router(_create_memory_pipeline_router(_handler, get_active_workspace_id=lambda: "ws-active"))
    client = TestClient(app)

    response = client.get("/api/memory/pipeline/query", params={"query": "hello"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "workspace_id": "ws-active", "scope": "workspace"}
    assert captured["workspace_id"] == "ws-active"
    assert captured["scope"] == "workspace"
