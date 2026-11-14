from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from database.models import Base
from database.repository import DatabaseRepository
from modules.agent.prompt_assembly import build_prompt_assembly
from routes.companion_api import create_companion_router


@pytest.fixture
def companion_client(tmp_path):
    db_path = tmp_path / "companion-persona.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    repo = DatabaseRepository(db_path)
    repo.create_companion("default", "Default", persona_prompt="EXISTING_PERSONA", model_type="vrm", model_id="existing-model")
    repo.create_workspace("scene", "Scene")
    app = FastAPI()
    app.include_router(create_companion_router(lambda: repo))
    with TestClient(app) as client:
        yield client, repo
    repo.close()


def test_patch_null_persona_clears_database_and_prompt(companion_client) -> None:
    client, repo = companion_client

    response = client.patch("/api/companions/default", json={"persona_prompt": None})

    assert response.status_code == 200
    assert response.json()["persona_prompt"] is None
    assert repo.get_companion("default")["persona_prompt"] is None
    compiled = build_prompt_assembly(
        db_repo=repo,
        generation_mgr=None,
        workspace_id="scene",
        session_id="persona-clear-test",
        messages=[],
    )
    assert all("id=companion_persona " not in message["content"] for message in compiled)


@pytest.mark.parametrize("payload", [{}, {"name": "Renamed"}])
def test_patch_omitted_persona_preserves_existing_persona(companion_client, payload) -> None:
    client, repo = companion_client

    response = client.patch("/api/companions/default", json=payload)

    assert response.status_code == 200
    assert repo.get_companion("default")["persona_prompt"] == "EXISTING_PERSONA"


@pytest.mark.parametrize("value", ["", "REPLACED_PERSONA"])
def test_patch_persona_accepts_empty_and_replacement_text(companion_client, value) -> None:
    client, repo = companion_client

    response = client.patch("/api/companions/default", json={"persona_prompt": value})

    assert response.status_code == 200
    assert response.json()["persona_prompt"] == value
    assert repo.get_companion("default")["persona_prompt"] == value


def test_patch_null_only_clears_allowlisted_persona(companion_client) -> None:
    client, repo = companion_client
    original = repo.get_companion("default")
    payload = {field: None for field in [
        "name", "model_type", "model_id", "avatar", "voice_profile", "temperament", "attachment_style", "support_style",
        "emotion_state", "affinity_state", "energy_state", "trust_state", "intimacy_state", "interruptibility_state", "fatigue_state",
    ]}
    payload["persona_prompt"] = None

    response = client.patch("/api/companions/default", json=payload)

    assert response.status_code == 200
    saved = repo.get_companion("default")
    assert saved["persona_prompt"] is None
    for field in payload:
        if field != "persona_prompt":
            assert saved[field] == original[field]
