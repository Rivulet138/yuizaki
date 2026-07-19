from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import realtime_api


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, str, str]] = []

    def get_workspace_companion(self, _workspace_id: str):
        return None

    def list_workspaces(self):
        return [{"id": "default", "system_prompt": ""}]

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        _tokens: int,
        model: str,
        workspace_id: str,
    ):
        record = {
            "id": len(self.saved) + 1,
            "session_id": session_id,
            "role": role,
            "content": content,
            "model": model,
            "timestamp": "2026-07-18T00:00:00+00:00",
        }
        self.saved.append((session_id, role, content, model, workspace_id))
        return record

    def save_message_pair(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        *,
        model: str,
        workspace_id: str,
    ):
        return (
            self.save_message(session_id, "user", user_content, 0, model, workspace_id),
            self.save_message(session_id, "assistant", assistant_content, 0, model, workspace_id),
        )


def build_client(config, repository: FakeRepository | None = None) -> TestClient:
    repository = repository or FakeRepository()
    app = FastAPI()
    app.include_router(
        realtime_api.create_realtime_router(
            get_config=lambda: config,
            get_db_repo=lambda: repository,
            get_active_workspace_id=lambda: "default",
        )
    )
    return TestClient(app)


def test_realtime_requires_a_dedicated_or_official_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = SimpleNamespace(
        llm=SimpleNamespace(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="deepseek-secret",
        )
    )
    response = build_client(config).post(
        "/api/realtime/client-secret",
        json={"workspace_id": "default", "session_id": "voice"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == "realtime_not_configured"


def test_realtime_mints_ephemeral_secret_without_returning_server_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-only")
    captured = {}

    async def fake_mint(**kwargs):
        captured.update(kwargs)
        return {"value": "ek_short_lived", "expires_at": 123456}

    monkeypatch.setattr(realtime_api, "mint_realtime_client_secret", fake_mint)
    config = SimpleNamespace(llm=SimpleNamespace(provider="deepseek", base_url="", api_key=""))
    response = build_client(config).post(
        "/api/realtime/client-secret",
        json={"workspace_id": "default", "session_id": "voice"},
    )

    assert response.status_code == 200
    assert response.json()["client_secret"] == "ek_short_lived"
    assert "sk-server-only" not in response.text
    assert captured["api_key"] == "sk-server-only"
    assert "realtime_voice_boundary" in captured["instructions"]
    assert "source=backend" in captured["instructions"]
    assert captured["instructions"].index("order=220") < captured["instructions"].index("order=225")


def test_realtime_safety_identifier_is_stable_and_does_not_expose_the_api_key(monkeypatch):
    monkeypatch.delenv("YUIZAKI_OPENAI_SAFETY_IDENTIFIER", raising=False)

    first = realtime_api.resolve_realtime_safety_identifier("sk-server-only")
    second = realtime_api.resolve_realtime_safety_identifier("sk-server-only")

    assert first == second
    assert first.startswith("yuizaki_")
    assert "sk-server-only" not in first


def test_realtime_rejects_a_non_active_workspace(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-only")
    config = SimpleNamespace(llm=SimpleNamespace(provider="chatgpt", base_url="", api_key=""))
    response = build_client(config).post(
        "/api/realtime/client-secret",
        json={"workspace_id": "other", "session_id": "voice"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"


def test_realtime_transcript_is_ordered_and_idempotent(monkeypatch):
    monkeypatch.setenv("YUIZAKI_REALTIME_MODEL", "gpt-realtime-test")
    repository = FakeRepository()
    config = SimpleNamespace(llm=SimpleNamespace(provider="chatgpt", base_url="", api_key=""))
    client = build_client(config, repository)
    payload = {
        "workspace_id": "default",
        "session_id": "voice-session",
        "turn_id": "turn-1",
        "user_text": "你好",
        "assistant_text": "我在。",
    }

    first = client.post("/api/realtime/transcript", json=payload)
    duplicate = client.post("/api/realtime/transcript", json=payload)

    assert first.status_code == 200
    assert first.json()["status"] == "saved"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert [record[1] for record in repository.saved] == ["user", "assistant"]
    assert all(record[3] == "gpt-realtime-test" for record in repository.saved)
