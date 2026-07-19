from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from i18n import set_locale
from routes.i18n import router as i18n_router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(i18n_router)
    return TestClient(app)


def test_i18n_locale_update_rejects_unsupported_locale():
    set_locale("zh-CN")
    client = _build_client()

    response = client.post("/api/i18n/locale", params={"locale": "fr-FR"})

    assert response.status_code == 400
    assert response.json()["status"] == "error"
    assert response.json()["locale"] == "zh-CN"


def test_i18n_locale_update_accepts_supported_locale():
    set_locale("zh-CN")
    client = _build_client()

    response = client.post("/api/i18n/locale", params={"locale": "ja-JP"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["locale"] == "ja-JP"
    set_locale("zh-CN")
