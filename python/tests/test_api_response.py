from types import SimpleNamespace

import pytest
from app_factory import create_app
from database.repository import DatabaseError, NotFoundError
from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient
from modules.system.api_response import error_response
from pydantic import BaseModel
from routes.companion_api import create_companion_router


def test_error_response_has_canonical_and_legacy_fields() -> None:
    app = FastAPI()

    @app.get("/failure")
    def failure():
        return error_response(
            code="unknown_effect",
            message="Outcome is unknown",
            status_code=409,
            details={"operation": "send"},
            request_id="req-1",
        )

    response = TestClient(app).get("/failure")
    assert response.status_code == 409
    assert response.json() == {
        "error": "unknown_effect",
        "code": "unknown_effect",
        "message": "Outcome is unknown",
        "details": {"operation": "send"},
        "retryable": False,
        "request_id": "req-1",
    }


def test_app_factory_normalizes_http_exception_and_preserves_detail() -> None:
    app = create_app()

    @app.get("/failure")
    def failure() -> None:
        raise HTTPException(
            status_code=409,
            detail={"error": "session_mismatch", "message": "Session does not match", "active": "ws-1"},
        )

    response = TestClient(app).get("/failure")
    assert response.status_code == 409
    assert response.json() == {
        "error": "session_mismatch",
        "code": "session_mismatch",
        "message": "Session does not match",
        "retryable": False,
        "detail": {"error": "session_mismatch", "message": "Session does not match", "active": "ws-1"},
    }


def test_app_factory_validation_does_not_echo_input_or_context() -> None:
    app = create_app()

    class Payload(BaseModel):
        count: int

    @app.post("/payload")
    def payload(body: Payload, limit: int = Query(ge=1)) -> dict[str, int]:
        return {"count": body.count + limit}

    response = TestClient(app).post("/payload?limit=0", json={"count": "secret-value"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["detail"] == body["details"]["errors"]
    assert "secret-value" not in response.text
    assert all("input" not in error and "ctx" not in error for error in body["details"]["errors"])


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/companions"), ("GET", "/api/companions/missing"),
    ("POST", "/api/companions"), ("PATCH", "/api/companions/missing"),
    ("DELETE", "/api/companions/missing"),
])
def test_companion_unavailable_preserves_legacy_error(method: str, path: str) -> None:
    app = create_app()
    app.include_router(create_companion_router(lambda: None))
    response = TestClient(app).request(method, path, json={})
    assert response.status_code == 503
    assert response.json()["error"] == "Database not initialized"
    assert response.json()["code"] == "database_not_initialized"


def test_relationship_history_has_stable_unavailable_capability_response() -> None:
    app = create_app()
    app.include_router(create_companion_router(lambda: None))

    response = TestClient(app).get("/api/companions/default/relationship-history")

    assert response.status_code == 501
    assert response.json() == {
        "error": "relationship_history_unavailable",
        "code": "relationship_history_unavailable",
        "message": "Relationship history is unavailable in this runtime",
        "retryable": False,
    }


def test_companion_business_errors_preserve_legacy_fields() -> None:
    def fail_create(**_kwargs):
        raise DatabaseError("Cannot create companion")

    def fail_update(*_args):
        raise NotFoundError("Companion is missing")

    app = create_app()
    repo = SimpleNamespace(get_companion=lambda _id: None, create_companion=fail_create, update_companion=fail_update)
    app.include_router(create_companion_router(lambda: repo))
    client = TestClient(app)
    for response, status, code, legacy in (
        (client.get("/api/companions/missing"), 404, "companion_not_found", "companion_not_found"),
        (client.post("/api/companions", json={}), 400, "database_error", "Cannot create companion"),
        (client.patch("/api/companions/missing", json={}), 404, "companion_not_found", "Companion is missing"),
    ):
        assert response.status_code == status
        assert response.json()["code"] == code
        assert response.json()["error"] == legacy
