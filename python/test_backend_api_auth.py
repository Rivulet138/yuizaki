from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from modules.system.backend_api_auth import backend_api_auth_required, verify_backend_api_authorization


def _build_client(token: str) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        client_host = request.client.host if request.client else None
        if backend_api_auth_required(request.url.path, token, client_host=client_host):
            allowed, message = verify_backend_api_authorization(
                request.headers.get("authorization"),
                token,
                request.headers.get("x-yuizaki-backend-token"),
                client_host=client_host,
            )
            if not allowed:
                return JSONResponse({"error": "unauthorized", "message": message}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/workspaces")
    async def workspaces():
        return {"workspaces": []}

    @app.get("/memory/docs")
    async def memory_docs():
        return {"docs": []}

    @app.get("/vision/ocr")
    async def vision_ocr():
        return {"ok": True}

    @app.get("/audio/sample.wav")
    async def audio():
        return {"ok": True}

    @app.get("/socket.io/")
    async def socket_io():
        return {"ok": True}

    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_backend_api_auth_fails_closed_without_token_by_default(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)
    client = _build_client("")

    response = client.get("/api/workspaces")

    assert response.status_code == 401
    assert response.json()["message"] == "Backend API token is not configured"


def test_backend_api_auth_can_be_explicitly_disabled_for_local_dev(monkeypatch):
    monkeypatch.setenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "1")
    client = _build_client("")

    response = client.get("/api/workspaces")

    assert response.status_code == 200


def test_backend_api_auth_rejects_missing_or_invalid_token_for_protected_paths():
    client = _build_client("secret-token")

    missing = client.get("/api/workspaces")
    invalid = client.get("/memory/docs", headers={"Authorization": "Bearer wrong-token"})

    assert missing.status_code == 401
    assert missing.json()["message"] == "Missing backend API token"
    assert invalid.status_code == 401
    assert invalid.json()["message"] == "Invalid backend API token"


def test_backend_api_auth_allows_valid_token_for_protected_paths():
    client = _build_client("secret-token")

    response = client.get("/api/workspaces", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200


def test_backend_api_auth_protects_vision_routes():
    client = _build_client("secret-token")

    missing = client.get("/vision/ocr")
    valid = client.get("/vision/ocr", headers={"x-yuizaki-backend-token": "secret-token"})

    assert missing.status_code == 401
    assert valid.status_code == 200


def test_backend_api_auth_allows_dedicated_backend_token_header_alongside_business_auth():
    client = _build_client("secret-token")

    response = client.get(
        "/api/workspaces",
        headers={
            "Authorization": "Bearer summary-admin-token",
            "x-yuizaki-backend-token": "secret-token",
        },
    )

    assert response.status_code == 200


def test_backend_api_auth_keeps_health_audio_and_socket_public():
    client = _build_client("secret-token")

    assert client.get("/health").status_code == 200
    assert client.get("/audio/sample.wav").status_code == 200
    assert client.get("/socket.io/").status_code == 200
