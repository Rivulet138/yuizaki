from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.core.config import AppConfig, _clean_optional_secret, SUMMARY_ADMIN_TOKEN_PLACEHOLDERS
from modules.system import DynamicConfigManager, SettingsStore
from modules.system.settings_api import SettingsAPI, router
from modules.system.settings_schema import MemorySettingsModel


async def _assert_event_loop_responsive(coro: Any) -> Any:
    slow_task = asyncio.create_task(coro)
    started = time.perf_counter()
    await asyncio.sleep(0.01)
    latency_ms = (time.perf_counter() - started) * 1000
    result = await slow_task

    assert latency_ms < 50
    return result


def test_memory_settings_preserve_sqlite_environment_default(monkeypatch):
    monkeypatch.setattr("modules.system.settings_schema.env_config.memory.backend", "sqlite")

    assert MemorySettingsModel().backend == "sqlite"


def _build_client(tmpdir: str, admin_token: str = "") -> tuple[TestClient, SettingsStore]:
    store = SettingsStore(str(Path(tmpdir) / "settings.json"))
    config = None
    if admin_token:
        config = AppConfig()
        config.summary.admin_token = admin_token
    api = SettingsAPI(store, DynamicConfigManager(), config=config)
    api.init_api()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), store


def test_settings_router_rollback_route_is_not_captured_by_dynamic_key_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        patch = client.patch("/api/settings/", json={"system": {"language": "en", "theme": "dark"}})
        assert patch.status_code == 200

        rollback = client.post("/api/settings/rollback", params={"steps": 1})

        assert rollback.status_code == 200
        assert rollback.json()["status"] == "rolled_back"
        assert store.get("system.language") == "zh-CN"


def test_settings_router_rollback_does_not_restore_old_credentials():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        first = client.patch(
            "/api/settings/",
            json={"llm": {"provider": "deepseek", "api_key": "first-secret"}},
        )
        second = client.patch(
            "/api/settings/",
            json={"llm": {"api_key": "current-secret"}, "system": {"theme": "dark"}},
        )
        rollback = client.post("/api/settings/rollback", params={"steps": 1})

        assert first.status_code == 200
        assert second.status_code == 200
        assert rollback.status_code == 200
        assert store.get("llm.api_key") == "current-secret"
        assert store.get("system.theme") == "light"


def test_settings_router_delete_resets_schema_backed_setting():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        patch = client.patch("/api/settings/", json={"llm": {"timeout": 12.0}})
        assert patch.status_code == 200

        reset = client.delete("/api/settings/llm.timeout")

        assert reset.status_code == 200
        assert reset.json()["status"] == "reset"
        assert store.get("llm.timeout") == 60.0


def test_settings_router_lists_llm_models_without_persisting_credentials(monkeypatch):
    captured = {}

    async def fake_fetch_available_models(base_url: str, api_key: str, timeout: float, provider: str = "custom"):
        captured.update({"base_url": base_url, "api_key": api_key, "timeout": timeout, "provider": provider})
        return ["gpt-test-a", "gpt-test-b"]

    monkeypatch.setattr("modules.system.settings_api.fetch_available_models", fake_fetch_available_models)

    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.post(
            "/api/settings/llm/models",
            json={"provider": "claude", "base_url": "https://api.anthropic.com/v1/messages", "api_key": "test-key", "timeout": 12},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["models"] == ["gpt-test-a", "gpt-test-b"]
        assert captured == {"base_url": "https://api.anthropic.com/v1", "api_key": "test-key", "timeout": 12.0, "provider": "claude"}
        assert store.get("llm.base_url") is None


def test_settings_router_persists_provider_aware_llm_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch(
            "/api/settings/",
            json={"llm": {"provider": "claude", "base_url": "https://api.anthropic.com/v1/messages", "model": "claude-sonnet-4-5"}},
        )

        assert response.status_code == 200
        assert store.get("llm.provider") == "claude"
        assert store.get("llm.base_url") == "https://api.anthropic.com/v1"
        assert store.get("llm.model") == "claude-sonnet-4-5"


def test_settings_router_persists_provider_scoped_llm_profiles_and_clears_local_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch(
            "/api/settings/",
            json={
                "llm": {
                    "provider": "ollama",
                    "base_url": "http://localhost:11434/v1",
                    "api_key": "should-not-stick",
                    "model": "llama3.2",
                    "profiles": {
                        "deepseek": {
                            "provider": "deepseek",
                            "base_url": "https://api.deepseek.com/v1",
                            "api_key": "deepseek-key",
                            "model": "deepseek-chat",
                        },
                        "ollama": {
                            "provider": "ollama",
                            "base_url": "http://localhost:11434/v1",
                            "api_key": "local-key",
                            "model": "llama3.2",
                        },
                        "lm-studio": {
                            "base_url": "http://localhost:1234/v1",
                            "api_key": "lm-key",
                            "model": "local-model",
                        },
                    },
                }
            },
        )

        assert response.status_code == 200
        assert store.get("llm.provider") == "ollama"
        assert store.get("llm.api_key") == ""
        assert store.get("llm.profiles.deepseek.api_key") == "deepseek-key"
        assert store.get("llm.profiles.ollama.api_key") == ""
        assert store.get("llm.profiles.lmstudio.api_key") == ""
        assert store.get("llm.profiles.lm-studio") is None


def test_settings_router_rejects_removed_tts_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch(
            "/api/settings/",
            json={
                "tts": {
                    "provider": "legacy-tts",
                    "genie_character": "feibi",
                    "base_url": "http://127.0.0.1:9880",
                    "timeout": 45,
                    "speed": 1.25,
                    "volume": 2,
                    "voice": "zh-CN-XiaoxiaoNeural",
                    "profiles": {
                        "edge": {
                            "provider": "edge",
                            "voice": "zh-CN-XiaoxiaoNeural",
                            "lang": "zh",
                        },
                        "legacy-tts": {
                            "provider": "legacy-tts",
                            "genie_character": "feibi",
                            "ref_audio": "E:/voice/ref.wav",
                            "ref_text": "你好",
                            "lang": "zh",
                        },
                    },
                }
            },
        )

        assert response.status_code == 422
        for field in ("base_url", "timeout", "speed", "volume", "voice", "profiles"):
            assert store.get(f"tts.{field}") is None


def test_settings_router_exposes_tts_runtime_status():
    class FakeTtsClient:
        async def test_connection(self) -> dict[str, object]:
            return {"ok": True}

        def status_snapshot(self) -> dict[str, object]:
            return {
                "provider": "genie-tts",
                "available": True,
                "loading": False,
                "warming_up": False,
                "warmup_done": True,
                "character": "feibi",
                "last_load_ms": 12.3,
                "last_warmup_ms": 45.6,
                "last_error": None,
                "capabilities": {
                    "provider": "genie-tts",
                    "locality": "local",
                    "input_text_streaming": False,
                    "output_audio_streaming": True,
                    "output_transport": "pcm_s16le",
                    "alignment": "none",
                    "viseme_vocabulary": [],
                    "warmup": True,
                    "cancellation": "cooperative",
                },
            }

    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        fake_tts = FakeTtsClient()
        api = SettingsAPI(
            store,
            DynamicConfigManager(),
            config=AppConfig(),
            tts_client_provider=lambda: fake_tts,
        )
        api.init_api()
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/settings/tts/status")

        assert response.status_code == 200
        assert response.json()["available"] is True
        assert response.json()["warmup_done"] is True
        assert response.json()["character"] == "feibi"
        assert response.json()["last_warmup_ms"] == 45.6
        assert response.json()["capabilities"]["output_transport"] == "pcm_s16le"


def test_settings_router_reports_known_tts_capabilities_without_runtime_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        api = SettingsAPI(
            store,
            DynamicConfigManager(),
            config=AppConfig(),
            tts_client_provider=lambda: None,
        )
        api.init_api()
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/settings/tts/status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "genie-tts"
        assert payload["available"] is False
        assert payload["capabilities"] == {
            "provider": "genie-tts",
            "locality": "local",
            "input_text_streaming": False,
            "output_audio_streaming": False,
            "output_transport": "unavailable",
            "alignment": "none",
            "viseme_vocabulary": [],
            "warmup": True,
            "cancellation": "cooperative",
        }


def test_settings_router_exposes_llm_preconnect_status_without_credentials():
    class FakeLlmClient:
        async def test_connection(self) -> dict[str, object]:
            return {"ok": True}

        def status_snapshot(self) -> dict[str, object]:
            return {
                "available": True,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "preconnect_running": False,
                "preconnect_attempts": 2,
                "last_preconnect_elapsed_ms": 81.5,
                "last_preconnect_http_status": 200,
                "last_preconnect_error": None,
            }

    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        api = SettingsAPI(
            store,
            DynamicConfigManager(),
            config=AppConfig(),
            llm_client_provider=lambda: FakeLlmClient(),
        )
        api.init_api()
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/settings/llm/status")

        assert response.status_code == 200
        assert response.json()["provider"] == "deepseek"
        assert response.json()["preconnect_attempts"] == 2
        assert response.json()["last_preconnect_elapsed_ms"] == 81.5
        assert "api_key" not in response.json()


def test_settings_router_queues_tts_runtime_warmup():
    class FakeTtsClient:
        def __init__(self) -> None:
            self.warmup_calls: list[dict[str, object]] = []

        async def test_connection(self) -> dict[str, object]:
            return {"ok": True}

        async def warmup(self, *, background: bool = False, force: bool = False) -> bool:
            self.warmup_calls.append({"background": background, "force": force})
            return True

        def status_snapshot(self) -> dict[str, object]:
            return {
                "available": True,
                "loading": False,
                "warming_up": True,
                "warmup_running": True,
                "warmup_done": False,
                "character": "feibi",
            }

    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        fake_tts = FakeTtsClient()
        api = SettingsAPI(
            store,
            DynamicConfigManager(),
            config=AppConfig(),
            tts_client_provider=lambda: fake_tts,
        )
        api.init_api()
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post("/api/settings/tts/warmup")

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["queued"] is True
        assert response.json()["runtime"]["warmup_running"] is True
        assert fake_tts.warmup_calls == [{"background": True, "force": False}]


def test_settings_router_exports_current_settings():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, _store = _build_client(tmpdir)

        patch = client.patch("/api/settings/", json={"llm": {"base_url": "https://api.example/v1", "api_key": "", "model": "gpt-test"}})
        response = client.get("/api/settings/export")

        assert patch.status_code == 200
        assert response.status_code == 200
        assert response.headers["content-disposition"] == 'attachment; filename="yuizaki-llm-settings.json"'
        data = response.json()
        assert data["llm"]["base_url"] == "https://api.example/v1"
        assert data["llm"]["api_key"] == ""
        assert data["llm"]["model"] == "gpt-test"


def test_settings_router_imports_partial_llm_profile_payload():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.post(
            "/api/settings/import",
            json={"llm": {"base_url": "https://api.example/v1", "api_key": "", "model": "gpt-test"}},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "imported"
        assert store.get("llm.base_url") == "https://api.example/v1"
        assert store.get("llm.api_key") == ""
        assert store.get("llm.model") == "gpt-test"
        assert store.get("tts.lang") == "ja"


def test_settings_router_imports_lightweight_llm_connection_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.post(
            "/api/settings/import",
            json={
                "kind": "yuizaki-llm-profile",
                "version": 1,
                "provider": "custom",
                "connectionProfile": {
                    "baseUrl": "https://models.example/v1",
                    "apiKey": "",
                    "modelName": "gpt-profile",
                    "maxTokens": 4096,
                    "temperature": 0.6,
                }
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "imported"
        assert store.get("llm.base_url") == "https://models.example/v1"
        assert store.get("llm.api_key") == ""
        assert store.get("llm.model") == "gpt-profile"
        assert store.get("llm.default_max_output_tokens") == 4096
        assert store.get("llm.temperature") == 0.6


def test_settings_router_imports_silly_tavern_sampler_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.post(
            "/api/settings/import",
            json={
                "temperature": 1.2,
                "frequency_penalty": 0.2,
                "presence_penalty": 0,
                "top_p": 0.9,
                "top_k": 500,
                "min_p": 0,
                "repetition_penalty": 1,
                "openai_max_context": 1145140,
                "openai_max_tokens": 65535,
                "prompts": [{"content": "not imported"}],
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "imported"
        assert store.get("llm.temperature") == 1.2
        assert store.get("llm.frequency_penalty") == 0.2
        assert store.get("llm.presence_penalty") == 0
        assert store.get("llm.top_p") == 0.9
        assert store.get("llm.top_k") == 500
        assert store.get("llm.min_p") == 0
        assert store.get("llm.repetition_penalty") == 1
        assert store.get("llm.context_max_tokens") == 1145140
        assert store.get("llm.default_max_output_tokens") == 65535
        assert store.get("prompts") is None


def test_settings_router_import_rejects_non_object_payload():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, _store = _build_client(tmpdir)

        response = client.post("/api/settings/import", json=["bad"])

        assert response.status_code == 422


def test_settings_router_redacts_secret_values_from_history_and_key_responses():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, _store = _build_client(tmpdir)

        set_response = client.post("/api/settings/llm.api_key", json="super-secret-key")
        history_response = client.get("/api/settings/history")
        key_response = client.get("/api/settings/llm.api_key")

        assert set_response.status_code == 200
        assert set_response.json()["value"] == "<redacted>"
        assert key_response.status_code == 200
        assert key_response.json()["value"] == "<redacted>"
        assert history_response.status_code == 200
        history_payload = history_response.json()
        assert "<redacted>" in str(history_payload)
        assert "super-secret-key" not in str(history_payload)


def test_settings_router_rejects_values_outside_frontend_option_contract():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, _store = _build_client(tmpdir)

        invalid_cases = [
            {"tts": {"lang": "fr"}},
            {"asr": {"sherpa_provider": "directml"}},
            {"summary": {"quality_scorer_mode": "hybrid"}},
            {"memory": {"backend": "pinecone"}},
            {"system": {"theme": "contrast"}},
        ]

        for payload in invalid_cases:
            response = client.patch("/api/settings/", json=payload)
            assert response.status_code == 422, f"Expected 422 for {payload}, got {response.status_code}"

        # Verify none of the invalid values leaked through: read via validated schema
        validated = client.get("/api/settings/")
        assert validated.status_code == 200
        data = validated.json()
        assert data["tts"]["lang"] == "ja"
        assert data["asr"]["sherpa_provider"] == "cpu"
        assert "whisper_model" not in data["asr"]
        assert "whisper_device" not in data["asr"]
        assert "whisper_compute" not in data["asr"]
        assert data["summary"]["quality_scorer_mode"] == "rule"
        assert data["memory"]["backend"] == "sqlite"
        assert data["system"]["language"] == "zh-CN"
        assert data["system"]["theme"] == "light"


def test_settings_router_accepts_japanese_interface_locale():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch("/api/settings/", json={"system": {"language": "ja-JP"}})

        assert response.status_code == 200
        assert store.get("system.language") == "ja-JP"


def test_settings_router_preserves_asr_http_provider_selection():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch(
            "/api/settings/",
            json={"asr": {"provider": "openai-compatible", "base_url": "http://asr.local/v1", "api_key": "secret"}},
        )

        assert response.status_code == 200
        assert store.get("asr.provider") == "openai-compatible"
        assert store.get("asr.base_url") == "http://asr.local/v1"
        assert store.get("asr.api_key") == "secret"

        loaded = client.get("/api/settings/")
        assert loaded.status_code == 200
        assert loaded.json()["asr"]["provider"] == "openai-compatible"
        assert loaded.json()["asr"]["api_key"] == "********"
        persisted = Path(tmpdir, "settings.json").read_text(encoding="utf-8")
        assert "secret" not in persisted


def test_settings_router_secret_mask_preserves_existing_credential():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)
        first = client.patch(
            "/api/settings/",
            json={"llm": {"provider": "deepseek", "api_key": "deepseek-secret"}},
        )
        unchanged = client.patch(
            "/api/settings/",
            json={"llm": {"api_key": "********", "temperature": 0.3}},
        )

        assert first.status_code == 200
        assert unchanged.status_code == 200
        assert store.get("llm.api_key") == "deepseek-secret"
        assert store.get("llm.temperature") == 0.3
        assert "deepseek-secret" not in Path(tmpdir, "settings.json").read_text(encoding="utf-8")


def test_settings_router_accepts_qdrant_api_key_for_memory_backend():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch(
            "/api/settings/",
            json={
                "memory": {
                    "backend": "qdrant",
                    "qdrant_url": "https://qdrant.example.com",
                    "qdrant_api_key": "qk-secret",
                    "qdrant_collection": "yuizaki_memories",
                    "qdrant_timeout": 7.5,
                    "qdrant_auto_start": False,
                    "qdrant_docker_image": "qdrant/qdrant:v1.14.0",
                    "qdrant_docker_container": "yuizaki-qdrant-test",
                    "qdrant_docker_volume": "yuizaki-qdrant-test-storage",
                }
            },
        )

        assert response.status_code == 200
        assert store.get("memory.backend") == "qdrant"
        assert store.get("memory.qdrant_url") == "https://qdrant.example.com"
        assert store.get("memory.qdrant_api_key") == "qk-secret"
        assert store.get("memory.qdrant_collection") == "yuizaki_memories"
        assert store.get("memory.qdrant_timeout") == 7.5
        assert store.get("memory.qdrant_auto_start") is False
        assert store.get("memory.qdrant_docker_image") == "qdrant/qdrant:v1.14.0"
        assert store.get("memory.qdrant_docker_container") == "yuizaki-qdrant-test"
        assert store.get("memory.qdrant_docker_volume") == "yuizaki-qdrant-test-storage"


@pytest.mark.asyncio
async def test_settings_update_returns_before_slow_runtime_reload_finishes():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        config = AppConfig()
        reload_started = asyncio.Event()
        reload_done = asyncio.Event()

        async def slow_reload(changed: set[str]) -> None:
            assert changed == {"llm"}
            reload_started.set()
            await asyncio.sleep(0.25)
            reload_done.set()

        api = SettingsAPI(store, DynamicConfigManager(), config=config, reload_runtime_services=slow_reload)
        api.init_api()

        started = time.perf_counter()
        response = await api.update_settings({"llm": {"base_url": "https://api.example/v1", "model": "gpt-fast-save"}})
        elapsed = time.perf_counter() - started

        assert response.status == "success"
        assert response.runtime_changed == ["llm"]
        assert elapsed < 0.15
        assert reload_done.is_set() is False

        await asyncio.wait_for(reload_started.wait(), timeout=0.1)
        await api.wait_for_runtime_reload_idle()
        assert reload_done.is_set() is True


@pytest.mark.asyncio
async def test_repeated_identical_tts_settings_do_not_reload_runtime_twice():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        config = AppConfig()
        reload_calls: list[set[str]] = []

        async def reload_runtime(changed: set[str]) -> None:
            reload_calls.append(set(changed))

        api = SettingsAPI(store, DynamicConfigManager(), config=config, reload_runtime_services=reload_runtime)
        api.init_api()

        first = await api.update_settings({"tts": {"genie_model_dir": "E:/models/voice-a"}})
        await api.wait_for_runtime_reload_idle()
        second = await api.update_settings({"tts": {"genie_model_dir": "E:/models/voice-a"}})
        await api.wait_for_runtime_reload_idle()

        assert first.runtime_changed == ["tts"]
        assert second.runtime_changed == []
        assert reload_calls == [{"tts"}]


@pytest.mark.asyncio
async def test_settings_update_offloads_slow_json_save_from_event_loop():
    class SlowSaveSettingsStore(SettingsStore):
        def save(self) -> None:
            time.sleep(0.08)
            super().save()

    with tempfile.TemporaryDirectory() as tmpdir:
        store = SlowSaveSettingsStore(str(Path(tmpdir) / "settings.json"))
        api = SettingsAPI(store, DynamicConfigManager(), config=AppConfig())
        api.init_api()

        response = await _assert_event_loop_responsive(
            api.update_settings({"llm": {"base_url": "https://api.example/v1", "model": "gpt-fast-save"}})
        )

        assert response.status == "success"
        assert store.get("llm.base_url") == "https://api.example/v1"


@pytest.mark.asyncio
async def test_llm_sampling_patch_updates_config_without_reloading_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SettingsStore(str(Path(tmpdir) / "settings.json"))
        config = AppConfig()
        reload_calls: list[set[str]] = []

        async def reload_runtime(changed: set[str]) -> None:
            reload_calls.append(set(changed))

        api = SettingsAPI(store, DynamicConfigManager(), config=config, reload_runtime_services=reload_runtime)
        api.init_api()

        response = await api.update_settings({
            "llm": {
                "temperature": 0.4,
                "top_p": 0.8,
                "top_k": 320,
                "min_p": 0.05,
                "frequency_penalty": 0.3,
                "presence_penalty": 0.1,
                "repetition_penalty": 1.05,
            }
        })
        await api.wait_for_runtime_reload_idle()

        assert response.status == "success"
        assert response.runtime_changed == ["llm"]
        assert config.llm.temperature == 0.4
        assert config.llm.top_p == 0.8
        assert config.llm.top_k == 320
        assert config.llm.min_p == 0.05
        assert config.llm.frequency_penalty == 0.3
        assert config.llm.presence_penalty == 0.1
        assert config.llm.repetition_penalty == 1.05
        assert reload_calls == []


def test_settings_router_preserves_empty_qdrant_url_and_normalizes_docker_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, store = _build_client(tmpdir)

        response = client.patch(
            "/api/settings/",
            json={
                "memory": {
                    "backend": "qdrant",
                    "qdrant_url": "",
                    "qdrant_collection": "",
                    "qdrant_docker_image": "",
                    "qdrant_docker_container": "",
                    "qdrant_docker_volume": "",
                }
            },
        )

        assert response.status_code == 200
        assert store.get("memory.qdrant_url") == ""
        assert store.get("memory.qdrant_collection") == "memories"
        assert store.get("memory.qdrant_docker_image") == "qdrant/qdrant:v1.18.3"
        assert store.get("memory.qdrant_docker_container") == "yuizaki-qdrant"
        assert store.get("memory.qdrant_docker_volume") == "yuizaki-qdrant-storage"


def test_settings_router_requires_admin_token_when_configured():
    with tempfile.TemporaryDirectory() as tmpdir:
        client, _store = _build_client(tmpdir, admin_token="secret")

        unauthorized = client.get("/api/settings/")
        authorized = client.get("/api/settings/", headers={"Authorization": "Bearer secret"})

        assert unauthorized.status_code == 401
        assert authorized.status_code == 200


def test_template_admin_token_placeholder_is_treated_as_unset():
    assert _clean_optional_secret("your-admin-token-here", SUMMARY_ADMIN_TOKEN_PLACEHOLDERS) == ""
    assert _clean_optional_secret(" real-token ", SUMMARY_ADMIN_TOKEN_PLACEHOLDERS) == "real-token"
