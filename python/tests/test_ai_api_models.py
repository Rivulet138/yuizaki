from __future__ import annotations

import logging
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.ai_api import create_ai_router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        create_ai_router(
            get_config=lambda: SimpleNamespace(llm=SimpleNamespace(model="test-model")),
            get_generation_mgr=lambda: None,
            get_llm_client=lambda: None,
            get_svc_client=lambda: None,
            get_agent_runtime=lambda: None,
            get_db_repo=lambda: None,
            get_relationship_writer=lambda: None,
            get_relationship_history=list,
            get_relationship_summary=dict,
            logger=logging.getLogger("test-ai-api-models"),
        )
    )
    return TestClient(app)


def test_models_supports_standard_get_and_legacy_post() -> None:
    client = _build_client()

    for response in (client.get("/v1/models"), client.post("/v1/models")):
        assert response.status_code == 200
        assert response.json() == {
            "object": "list",
            "data": [{"id": "test-model", "object": "model"}],
        }
