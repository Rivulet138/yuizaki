"""Test suite for system modules."""

import asyncio
import pytest
import tempfile
import json
from pathlib import Path
from modules.system import (
    ServiceManager,
    HealthChecker,
    SettingsStore,
    DynamicConfigManager,
    ConfigChangeListener,
    SlidingWindowRateLimiter,
)
from modules.system.settings_api import SettingsAPI
from modules.core.config import AppConfig
import modules.system.runtime_config as runtime_config


class TestServiceManager:
    """Test ServiceManager."""

    @pytest.mark.asyncio
    async def test_register_and_start_service(self):
        """Test registering and starting a service."""
        manager = ServiceManager()

        init_called = False
        async def init_service():
            nonlocal init_called
            init_called = True

        manager.register("test_service", init_service)
        assert "test_service" in manager.services

        success = await manager.start_all()
        assert success
        assert init_called

    @pytest.mark.asyncio
    async def test_service_cleanup(self):
        """Test service cleanup."""
        manager = ServiceManager()

        cleanup_called = False
        async def init_service():
            pass

        async def cleanup_service():
            nonlocal cleanup_called
            cleanup_called = True

        manager.register("test_service", init_service, cleanup_service)
        await manager.start_all()
        await manager.stop_all()
        assert cleanup_called

    def test_get_service_status(self):
        """Test getting service status."""
        manager = ServiceManager()

        async def init_service():
            pass

        manager.register("test_service", init_service)
        status = manager.get_status("test_service")
        assert status["name"] == "test_service"
        assert status["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_reregister_service_replaces_startup_order_entry(self):
        """Re-registering a service should not duplicate startup/shutdown order entries."""
        manager = ServiceManager()
        calls: list[str] = []

        async def first_init():
            calls.append("first")

        async def second_init():
            calls.append("second")

        manager.register("test_service", first_init)
        manager.register("test_service", second_init)

        assert manager.startup_order == ["test_service"]
        assert manager.shutdown_order == ["test_service"]

        success = await manager.start_all()

        assert success
        assert calls == ["second"]


class TestHealthChecker:
    """Test HealthChecker."""

    @pytest.mark.asyncio
    async def test_register_and_check(self):
        """Test registering and running health checks."""
        checker = HealthChecker()

        async def check_service():
            return True, "Service healthy"

        checker.register_check("test_service", check_service)
        status = await checker.check_all()
        assert status["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_degraded_health(self):
        """Test degraded health status."""
        checker = HealthChecker()

        async def check_healthy():
            return True, "Healthy"

        async def check_degraded():
            return False, "Degraded"

        checker.register_check("healthy", check_healthy)
        checker.register_check("degraded", check_degraded)
        status = await checker.check_all()
        assert status["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_unhealthy_status(self):
        """Test unhealthy status."""
        checker = HealthChecker()

        async def check_unhealthy():
            raise Exception("Service error")

        checker.register_check("unhealthy", check_unhealthy)
        status = await checker.check_all()
        assert status["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_timeout_is_bounded(self):
        """Test that one stalled check cannot block the health endpoint."""
        checker = HealthChecker(check_timeout_seconds=0.01)

        async def check_timeout():
            await asyncio.sleep(10)
            return True, "Should not complete"

        checker.register_check("timeout", check_timeout)
        status = await checker.check_all()

        assert status["status"] == "unhealthy"
        assert status["components"][0]["status"] == "unhealthy"
        assert "timed out" in status["components"][0]["message"]


class TestSettingsStore:
    """Test SettingsStore."""

    def test_get_and_set(self):
        """Test getting and setting values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            store.set("key1", "value1")
            assert store.get("key1") == "value1"

    def test_dot_notation(self):
        """Test dot notation for nested keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            store.set("section.key", "value")
            assert store.get("section.key") == "value"

    def test_save_and_load(self):
        """Test saving and loading settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store1 = SettingsStore(filepath)
            store1.set("key1", "value1")
            store1.save()

            store2 = SettingsStore(filepath)
            assert store2.get("key1") == "value1"

    def test_delete(self):
        """Test deleting settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            store.set("key1", "value1")
            assert store.delete("key1")
            assert store.get("key1") is None

    def test_export_import(self):
        """Test exporting and importing settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store1 = SettingsStore(str(Path(tmpdir) / "settings1.json"))
            store1.set("key1", "value1")
            store1.set("key2", "value2")

            export_path = str(Path(tmpdir) / "export.json")
            store1.export(export_path)

            store2 = SettingsStore(str(Path(tmpdir) / "settings2.json"))
            store2.import_settings(export_path)
            assert store2.get("key1") == "value1"
            assert store2.get("key2") == "value2"

    def test_provider_credentials_load_from_environment_without_plaintext_persistence(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "settings.json"
            filepath.write_text(
                json.dumps({"llm": {"provider": "deepseek", "api_key": ""}}),
                encoding="utf-8",
            )
            monkeypatch.setenv(
                "YUIZAKI_PROVIDER_CREDENTIALS_JSON",
                json.dumps({"llm.api_key": "environment-secret"}),
            )

            store = SettingsStore(str(filepath))
            assert store.get("llm.api_key") == "environment-secret"

            store.set("system.theme", "dark")
            store.save()

            persisted = json.loads(filepath.read_text(encoding="utf-8"))
            assert persisted["llm"]["api_key"] == ""
            assert "environment-secret" not in filepath.read_text(encoding="utf-8")


class TestSettingsApiValidation:
    @pytest.mark.asyncio
    async def test_update_settings_rejects_invalid_payload_without_persisting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            before = store.get_all()
            with pytest.raises(Exception):
                await api.update_settings({"unknown_section": {"x": 1}})

            assert store.get_all() == before

    @pytest.mark.asyncio
    async def test_import_settings_rejects_invalid_payload_without_persisting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            transfer_file = store.transfer_dir / "bad.json"
            transfer_file.write_text(json.dumps({"llm": {"timeout": "bad"}}), encoding="utf-8")

            before = store.get_all()
            with pytest.raises(Exception):
                await api.import_settings("bad.json")

            assert store.get_all() == before

    @pytest.mark.asyncio
    async def test_update_settings_requires_nested_schema_and_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            result = await api.update_settings({"llm": {"base_url": "https://example.com/v1", "model": "gpt-test"}})

            assert result.status == "success"
            assert store.get("llm.base_url") == "https://example.com/v1"
            assert store.get("llm.model") == "gpt-test"

    @pytest.mark.asyncio
    async def test_get_all_settings_rejects_removed_top_level_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            store.replace({"llm": {"base_url": "https://example.com/v1", "model": "gpt-test"}, "llm_api_key": "legacy-key"})
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            with pytest.raises(Exception):
                await api.get_all_settings()

    def test_init_api_applies_persisted_settings_to_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            store.replace({
                "llm": {
                    "base_url": "https://persisted.example/v1",
                    "api_key": "persisted-key",
                    "model": "gpt-persisted",
                    "temperature": 0.4,
                }
            })
            store.save()
            app_config = AppConfig()
            api = SettingsAPI(store, DynamicConfigManager(), config=app_config)

            api.init_api()

            assert app_config.llm.base_url == "https://persisted.example/v1"
            assert app_config.llm.api_key == "persisted-key"
            assert app_config.llm.model == "gpt-persisted"
            assert app_config.llm.temperature == 0.4

    @pytest.mark.asyncio
    async def test_import_settings_rejects_removed_top_level_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            transfer_file = store.transfer_dir / "legacy.json"
            transfer_file.write_text(
                json.dumps({"llm": {"base_url": "https://legacy.example/v1", "model": "gpt-legacy"}, "llm_api_key": "legacy-key"}),
                encoding="utf-8",
            )

            with pytest.raises(Exception):
                await api.import_settings("legacy.json")

    @pytest.mark.asyncio
    async def test_partial_runtime_patch_preserves_existing_runtime_siblings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            app_config = AppConfig()
            reloaded_sections: list[set[str]] = []

            async def reload_runtime_services(changed: set[str]) -> None:
                reloaded_sections.append(changed)

            api = SettingsAPI(store, dynamic, config=app_config, reload_runtime_services=reload_runtime_services)

            await api.update_settings({"llm": {"base_url": "https://runtime.example/v1", "api_key": "runtime-key", "model": "gpt-one"}})
            await api.update_settings({"llm": {"model": "gpt-two"}})
            await api.wait_for_runtime_reload_idle()

            assert store.get("llm.base_url") == "https://runtime.example/v1"
            assert store.get("llm.api_key") == "runtime-key"
            assert store.get("llm.model") == "gpt-two"
            assert app_config.llm.base_url == "https://runtime.example/v1"
            assert app_config.llm.api_key == "runtime-key"
            assert app_config.llm.model == "gpt-two"
            assert dynamic.get("llm") == {"model": "gpt-two"}
            assert reloaded_sections[-1] == {"llm"}

    @pytest.mark.asyncio
    async def test_asr_runtime_controls_are_normalized_before_persist_and_apply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            app_config = AppConfig()
            reloaded_sections: list[set[str]] = []

            async def reload_runtime_services(changed: set[str]) -> None:
                reloaded_sections.append(changed)

            api = SettingsAPI(store, dynamic, config=app_config, reload_runtime_services=reload_runtime_services)

            result = await api.update_settings(
                {
                    "asr": {
                        "vad_threshold": 2,
                        "vad_min_silence_ms": 5000,
                        "asr_partial_every": 0,
                    }
                }
            )
            await api.wait_for_runtime_reload_idle()

            expected = {
                "vad_threshold": 0.9,
                "vad_min_silence_ms": 1200,
                "asr_partial_every": 1,
            }
            assert result.status == "success"
            assert store.get("asr.vad_threshold") == expected["vad_threshold"]
            assert store.get("asr.vad_min_silence_ms") == expected["vad_min_silence_ms"]
            assert store.get("asr.asr_partial_every") == expected["asr_partial_every"]
            assert app_config.asr.vad_threshold == expected["vad_threshold"]
            assert app_config.asr.vad_min_silence_ms == expected["vad_min_silence_ms"]
            assert app_config.asr.asr_partial_every == expected["asr_partial_every"]
            assert dynamic.get("asr") == expected
            assert reloaded_sections[-1] == {"asr"}

    @pytest.mark.asyncio
    async def test_tts_patch_rejects_removed_provider_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            app_config = AppConfig()
            reloaded_sections: list[set[str]] = []

            async def reload_runtime_services(changed: set[str]) -> None:
                reloaded_sections.append(changed)

            api = SettingsAPI(store, dynamic, config=app_config, reload_runtime_services=reload_runtime_services)

            with pytest.raises(Exception):
                await api.update_settings({"tts": {"provider": "edge", "voice": "zh-CN-XiaoxiaoNeural"}})

            assert store.get("tts.voice") is None
            assert app_config.tts.provider == "genie-tts"
            assert app_config.tts.voice == "alloy"
            assert dynamic.get("tts") is None
            assert reloaded_sections == []

    @pytest.mark.asyncio
    async def test_rollback_changes_restores_persisted_settings_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            await api.update_settings({"llm": {"base_url": "https://one.example/v1", "model": "gpt-one"}})
            await api.update_settings({"llm": {"base_url": "https://two.example/v1", "model": "gpt-two"}})

            result = await api.rollback_changes(1)

            assert result.status == "rolled_back"
            assert store.get("llm.base_url") == "https://one.example/v1"
            assert store.get("llm.model") == "gpt-one"

            reloaded = SettingsStore(filepath)
            assert reloaded.get("llm.base_url") == "https://one.example/v1"
            assert reloaded.get("llm.model") == "gpt-one"

    @pytest.mark.asyncio
    async def test_rollback_changes_restores_non_runtime_settings_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            await api.update_settings({"system": {"language": "en", "theme": "dark"}})
            await api.update_settings({"system": {"language": "zh", "theme": "light"}})

            result = await api.rollback_changes(1)

            assert result.status == "rolled_back"
            assert store.get("system.language") == "en"
            assert store.get("system.theme") == "dark"

    @pytest.mark.asyncio
    async def test_delete_setting_resets_through_validated_commit_pipeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)

            await api.update_settings({"llm": {"timeout": 12.0}})
            result = await api.delete_setting("llm.timeout")

            assert result.status == "reset"
            assert store.get("llm.timeout") == 60.0
            assert dynamic.get("llm")["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_commit_restores_previous_settings_when_save_fails(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")
            store = SettingsStore(filepath)
            dynamic = DynamicConfigManager()
            api = SettingsAPI(store, dynamic)
            await api.update_settings({"llm": {"base_url": "https://one.example/v1", "model": "gpt-one"}})
            before = store.get_all()

            def fail_save():
                raise OSError("disk full")

            monkeypatch.setattr(store, "save", fail_save)

            with pytest.raises(OSError):
                await api.update_settings({"llm": {"base_url": "https://two.example/v1", "model": "gpt-two"}})

            assert store.get_all() == before
            assert dynamic.get("llm")["base_url"] == "https://one.example/v1"


class TestDynamicConfigManager:
    """Test DynamicConfigManager."""

    @pytest.mark.asyncio
    async def test_update_config(self):
        """Test updating configuration."""
        manager = DynamicConfigManager()
        await manager.update("key1", "value1")
        assert manager.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_listener_notification(self):
        """Test listener notification on config change."""
        manager = DynamicConfigManager()

        callback_called = False
        async def callback(key, old_value, new_value):
            nonlocal callback_called
            callback_called = True

        listener = ConfigChangeListener(callback)
        manager.register_listener(listener)
        await manager.update("key1", "value1")
        await asyncio.sleep(0.1)  # Allow async callback to complete
        assert callback_called

    @pytest.mark.asyncio
    async def test_change_history(self):
        """Test change history tracking."""
        manager = DynamicConfigManager()
        await manager.update("key1", "value1")
        await manager.update("key1", "value2")

        history = manager.get_history("key1")
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_rollback(self):
        """Test configuration rollback."""
        manager = DynamicConfigManager()
        await manager.update("key1", "value1")
        await manager.update("key1", "value2")

        manager.rollback(1)
        assert manager.get("key1") == "value1"


class TestRuntimeConfigReload:
    def test_apply_runtime_config_uses_canonical_online_asr_provider(self):
        app_config = AppConfig()

        changed = runtime_config.apply_runtime_config(
            app_config,
            {"asr": {"provider": "sherpa-onnx-online"}},
        )

        assert changed == {"asr"}
        assert app_config.asr.provider == "sherpa-onnx-online"

    def test_apply_runtime_config_updates_voice_runtime_fields(self):
        app_config = AppConfig()

        changed = runtime_config.apply_runtime_config(
            app_config,
            {
                "tts": {
                    "genie_character": "alice",
                    "genie_model_dir": "E:/models/alice",
                },
                "svc": {
                    "provider": "soulx-service",
                    "base_url": "http://127.0.0.1:7861",
                    "speaker_id": 2,
                    "pitch": -3,
                },
            },
        )

        assert changed == {"tts", "svc"}
        assert app_config.tts.genie_character == "alice"
        assert app_config.tts.genie_model_dir == "E:/models/alice"
        assert app_config.svc.provider == "soulx-service"
        assert app_config.svc.base_url == "http://127.0.0.1:7861"
        assert app_config.svc.speaker_id == 2
        assert app_config.svc.pitch == -3

    def test_apply_runtime_config_normalizes_llm_final_endpoint_url(self):
        app_config = AppConfig()

        changed = runtime_config.apply_runtime_config(
            app_config,
            {"llm": {"base_url": "https://api.example/v1/chat/completions"}},
        )

        assert changed == {"llm"}
        assert app_config.llm.base_url == "https://api.example/v1"

    def test_apply_runtime_config_updates_dedicated_vision_model(self):
        app_config = AppConfig()

        changed = runtime_config.apply_runtime_config(
            app_config,
            {
                "llm": {
                    "vision_enabled": True,
                    "vision_provider": "qwen",
                    "vision_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    "vision_api_key": "vision-key",
                    "vision_model": "vision-test",
                    "vision_timeout": 18,
                }
            },
        )

        assert changed == {"llm"}
        assert app_config.llm.vision_enabled is True
        assert app_config.llm.vision_provider == "qwen"
        assert app_config.llm.vision_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert app_config.llm.vision_api_key == "vision-key"
        assert app_config.llm.vision_model == "vision-test"
        assert app_config.llm.vision_timeout == 18

    @pytest.mark.asyncio
    async def test_reload_runtime_services_reinjects_fresh_clients_from_providers(self):
        injected: dict[str, object] = {}

        class SioServer:
            def inject_services(self, **kwargs):
                injected.update(kwargs)

        async def noop():
            return None

        reload_runtime_services = getattr(runtime_config, "reload_runtime_services")
        await reload_runtime_services(
            {"llm", "tts", "asr"},
            object(),
            "generation",
            SioServer(),
            "old-llm",
            "old-tts",
            "old-asr",
            noop,
            noop,
            noop,
            noop,
            noop,
            noop,
            noop,
            noop,
            lambda: "new-llm",
            lambda: "new-tts",
            lambda: "new-asr",
        )

        assert injected["llm_client"] == "new-llm"
        assert injected["vision_llm_client"] is None
        assert injected["tts_client"] == "new-tts"
        assert injected["asr_manager"] == "new-asr"
        assert injected["generation_mgr"] == "generation"


class TestSlidingWindowRateLimiter:
    """Test sliding-window rate limiter."""

    def test_allows_within_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=1.0)
        r1 = limiter.check("k")
        r2 = limiter.check("k")
        assert r1.allowed is True
        assert r2.allowed is True

    def test_blocks_over_limit(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=5.0)
        r1 = limiter.check("k")
        r2 = limiter.check("k")
        assert r1.allowed is True
        assert r2.allowed is False
        assert r2.retry_after > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
