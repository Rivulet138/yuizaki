from __future__ import annotations

from typing import Any, Callable, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.repository import DatabaseError, NotFoundError
from routes.companion_api import create_companion_router


_create_companion_router = cast(Callable[..., Any], create_companion_router)


class _FakeRepo:
    def __init__(self) -> None:
        self.updated: dict[str, object] | None = None

    def list_companions(self) -> list[dict[str, str]]:
        return [{"id": "comp-1", "name": "Demo"}]

    def get_companion(self, companion_id: str) -> dict[str, str] | None:
        if companion_id == "comp-1":
            return {"id": "comp-1", "name": "Demo"}
        if companion_id == "desk/pet":
            return {"id": "desk/pet", "name": "Slash Desk Pet"}
        return None

    def create_companion(self, companion_id: str, name: str, **kwargs: object) -> dict[str, object]:
        return {"id": companion_id, "name": name, **kwargs}

    def update_companion(self, companion_id: str, updates: dict[str, object]) -> dict[str, object]:
        self.updated = updates
        return {"id": companion_id, "name": "Demo", **updates}

    def list_workspaces_referencing_companion(self, companion_id: str) -> list[dict[str, object]]:
        return [{"id": "ws-1", "companion_profile_id": companion_id}]

    def delete_companion(self, companion_id: str) -> None:
        return None


def _build_client(repo: object | None = None) -> TestClient:
    repo = repo or _FakeRepo()
    app = FastAPI()
    app.include_router(
        _create_companion_router(
            lambda: repo,
            relationship_history_handler=lambda companion_id, limit: {
                "companion_id": companion_id,
                "events": [],
                "limit": limit,
            },
        )
    )
    return TestClient(app)


class _MissingCompanionRepo(_FakeRepo):
    def update_companion(self, companion_id: str, updates: dict[str, object]) -> dict[str, object]:
        raise NotFoundError(f"companion_not_found: {companion_id}")


class _InvalidCompanionRepo(_FakeRepo):
    def create_companion(self, companion_id: str, name: str, **kwargs: object) -> dict[str, object]:
        raise DatabaseError("duplicate companion")

    def update_companion(self, companion_id: str, updates: dict[str, object]) -> dict[str, object]:
        raise DatabaseError("invalid companion")


def test_companion_router_exposes_relationship_history_route():
    client = _build_client()

    response = client.get("/api/companions/comp-1/relationship-history", params={"limit": 7})

    assert response.status_code == 200
    assert response.json() == {
        "companion_id": "comp-1",
        "events": [],
        "limit": 7,
    }


def test_companion_routes_accept_encoded_slash_ids():
    client = _build_client()

    fetched = client.get("/api/companions/desk%2Fpet")
    history = client.get("/api/companions/desk%2Fpet/relationship-history", params={"limit": 3})
    updated = client.patch("/api/companions/desk%2Fpet", json={"name": "桌宠"})
    deleted = client.delete("/api/companions/desk%2Fpet")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == "desk/pet"
    assert history.status_code == 200
    assert history.json()["companion_id"] == "desk/pet"
    assert history.json()["limit"] == 3
    assert updated.status_code == 200
    assert updated.json()["id"] == "desk/pet"
    assert deleted.status_code == 200
    assert deleted.json()["rebound_workspaces"] == [{"id": "ws-1", "companion_profile_id": "desk/pet"}]


def test_companion_router_accepts_frontend_option_contract():
    client = _build_client()

    response = client.patch("/api/companions/comp-1", json={
        "model_type": "vrm",
        "temperament": "playful",
        "attachment_style": "attached",
        "support_style": "cheerful",
        "voice_profile": {"lang": "auto"},
        "trust_state": 0.8,
        "interruptibility_state": 0.25,
    })

    assert response.status_code == 200
    assert response.json()["model_type"] == "vrm"
    assert response.json()["voice_profile"] == {"lang": "auto"}


def test_companion_router_rejects_values_outside_frontend_option_contract():
    client = _build_client()

    invalid_cases = [
        {"model_type": "spine"},
        {"temperament": "icy"},
        {"attachment_style": "avoidant"},
        {"support_style": "strict"},
        {"voice_profile": {"lang": "fr"}},
        {"trust_state": 1.2},
        {"fatigue_state": -0.1},
    ]

    for payload in invalid_cases:
        response = client.patch("/api/companions/comp-1", json=payload)
        assert response.status_code == 422


def test_companion_router_maps_missing_update_to_404():
    client = _build_client(_MissingCompanionRepo())

    response = client.patch("/api/companions/missing", json={"name": "Missing"})

    assert response.status_code == 404
    assert response.json() == {"error": "companion_not_found: missing"}


def test_companion_router_maps_repository_errors_to_400():
    client = _build_client(_InvalidCompanionRepo())

    created = client.post("/api/companions", json={"id": "dup", "name": "Dup"})
    updated = client.patch("/api/companions/comp-1", json={"name": "Invalid"})

    assert created.status_code == 400
    assert created.json() == {"error": "duplicate companion"}
    assert updated.status_code == 400
    assert updated.json() == {"error": "invalid companion"}
