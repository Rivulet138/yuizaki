from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.system.backend_api_auth import verify_host_desktop_action_authorization
from modules.system.http_observability import install_backend_http_middleware


def test_host_desktop_action_requires_configured_host_token() -> None:
    assert verify_host_desktop_action_authorization("Bearer host", "", "backend") == (
        False,
        "Host desktop action token is not configured",
    )


def test_host_desktop_action_rejects_missing_or_malformed_authorization() -> None:
    assert verify_host_desktop_action_authorization(None, "host", "backend")[0] is False
    assert verify_host_desktop_action_authorization("Basic host", "host", "backend") == (
        False,
        "Invalid host desktop action token",
    )


def test_host_desktop_action_accepts_only_exact_host_token() -> None:
    assert verify_host_desktop_action_authorization("Bearer host", "host", "backend") == (True, "")
    assert verify_host_desktop_action_authorization("Bearer backend", "host", "backend")[0] is False
    assert verify_host_desktop_action_authorization("Bearer host ", "host", "backend") == (True, "")


def test_host_desktop_action_rejects_reused_backend_token_configuration() -> None:
    assert verify_host_desktop_action_authorization("Bearer same", "same", "same") == (
        False,
        "Host desktop action token must be distinct from backend API token",
    )


def test_desktop_action_http_middleware_requires_host_token(monkeypatch) -> None:
    monkeypatch.setenv("YUIZAKI_HOST_DESKTOP_ACTION_TOKEN", "host")
    app = FastAPI()

    @app.get("/api/desktop-actions/status")
    async def status() -> dict[str, bool]:
        return {"ok": True}

    install_backend_http_middleware(app, logger=logging.getLogger("test.backend-auth"), backend_api_token="backend")
    client = TestClient(app)

    assert client.get("/api/desktop-actions/status").status_code == 401
    assert client.get(
        "/api/desktop-actions/status",
        headers={"Authorization": "Bearer backend"},
    ).status_code == 401
    assert client.get(
        "/api/desktop-actions/status",
        headers={"Authorization": "Bearer host"},
    ).json() == {"ok": True}
