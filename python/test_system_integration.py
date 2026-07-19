"""Integration tests for system architecture."""

import asyncio
import pytest
import tempfile
from pathlib import Path
from modules.system import (
    ServiceManager,
    HealthChecker,
    SettingsStore,
    DynamicConfigManager,
)
from modules.core.config import AppConfig
from modules.system.settings_api import SettingsAPI


def test_cors_allows_put_for_memory_doc_edit_contract():
    app_source = (Path(__file__).parent / "app.py").read_text(encoding="utf-8")

    assert 'allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]' in app_source


class TestSystemIntegration:
    """Integration tests for system components."""

    @pytest.mark.asyncio
    async def test_full_service_lifecycle(self):
        """Test complete service lifecycle."""
        manager = ServiceManager()

        service_states = []

        async def init_service1():
            service_states.append("service1_init")

        async def cleanup_service1():
            service_states.append("service1_cleanup")

        async def init_service2():
            service_states.append("service2_init")

        async def cleanup_service2():
            service_states.append("service2_cleanup")

        manager.register("service1", init_service1, cleanup_service1)
        manager.register("service2", init_service2, cleanup_service2, depends_on=["service1"])

        # Start services
        success = await manager.start_all()
        assert success
        assert "service1_init" in service_states
        assert "service2_init" in service_states

        # Stop services
        await manager.stop_all()
        assert "service1_cleanup" in service_states
        assert "service2_cleanup" in service_states

    @pytest.mark.asyncio
    async def test_health_check_with_services(self):
        """Test health checks with running services."""
        manager = ServiceManager()
        checker = HealthChecker()

        service_running = False

        async def init_service():
            nonlocal service_running
            service_running = True

        async def cleanup_service():
            nonlocal service_running
            service_running = False

        async def check_service():
            return service_running, "Service running" if service_running else "Service stopped"

        manager.register("test_service", init_service, cleanup_service)
        checker.register_check("test_service", check_service)

        # Before starting
        status = await checker.check_all()
        assert status["status"] == "degraded"

        # After starting
        await manager.start_all()
        status = await checker.check_all()
        assert status["status"] == "healthy"

        # After stopping
        await manager.stop_all()
        status = await checker.check_all()
        assert status["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_config_and_settings_integration(self):
        """Test configuration and settings integration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            dynamic_config = DynamicConfigManager()

            # Load initial config
            config = AppConfig()
            assert config.llm.model is not None

            # Update settings
            settings_store.set("llm.model", "custom-model")
            settings_store.save()

            # Update dynamic config
            await dynamic_config.update("llm.model", "custom-model")

            # Verify
            assert settings_store.get("llm.model") == "custom-model"
            assert dynamic_config.get("llm.model") == "custom-model"

    @pytest.mark.asyncio
    async def test_service_failure_handling(self):
        """Test handling of service initialization failures."""
        manager = ServiceManager()

        async def failing_service():
            raise RuntimeError("Service initialization failed")

        async def dependent_service():
            pass

        manager.register("failing_service", failing_service)
        manager.register("dependent_service", dependent_service, depends_on=["failing_service"])

        success = await manager.start_all()
        assert not success

        status = manager.get_status()
        assert status["failing_service"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self):
        """Test concurrent health checks."""
        checker = HealthChecker()

        check_times = []

        async def slow_check():
            import time
            start = time.time()
            await asyncio.sleep(0.1)
            check_times.append(time.time() - start)
            return True, "Slow check complete"

        async def fast_check():
            return True, "Fast check complete"

        checker.register_check("slow", slow_check)
        checker.register_check("fast", fast_check)

        import time
        start = time.time()
        status = await checker.check_all()
        total_time = time.time() - start

        # Should run concurrently, so total time should be ~0.1s, not 0.2s
        assert total_time < 0.2
        assert status["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_settings_persistence_across_restarts(self):
        """Test settings persistence across restarts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = str(Path(tmpdir) / "settings.json")

            # First instance
            store1 = SettingsStore(filepath)
            store1.set("system.theme", "dark")
            store1.set("system.language", "zh")
            store1.save()

            # Second instance (simulating restart)
            store2 = SettingsStore(filepath)
            assert store2.get("system.theme") == "dark"
            assert store2.get("system.language") == "zh"

    @pytest.mark.asyncio
    async def test_settings_api_applies_runtime_only_after_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))
            dynamic = DynamicConfigManager()

            applied: list[set[str]] = []

            async def reload_runtime(changed: set[str]) -> None:
                applied.append(set(changed))

            class _Config:
                class llm:
                    base_url = "https://api.openai.com/v1"
                    api_key = ""
                    model = "gpt-3.5-turbo"

                class tts:
                    base_url = "http://127.0.0.1:9880"
                    ref_audio = ""
                    ref_text = ""
                    lang = "zh"

                class asr:
                    language = "zh"
                    vad_threshold = 0.5
                    vad_min_silence_ms = 300
                    asr_partial_every = 15

                class svc:
                    base_url = "http://127.0.0.1:6842"
                    speaker_id = 0
                    pitch = 0

                class summary:
                    trigger_messages = 24
                    keep_recent_messages = 8
                    item_max_chars = 140
                    rewrite_interval_messages = 6
                    quality_scorer_mode = "rule"
                    quality_score_cooldown_seconds = 300
                    quality_score_budget_per_hour = 20

            api = SettingsAPI(store, dynamic, config=_Config(), reload_runtime_services=reload_runtime)

            with pytest.raises(Exception):
                await api.update_settings({"summary": {"unknown_field": 1}})

            assert applied == []

            result = await api.update_settings({"summary": {"trigger_messages": 30}})
            await api.wait_for_runtime_reload_idle()
            assert result.runtime_applied == ["summary"]
            assert applied == [{"summary"}]

    @pytest.mark.asyncio
    async def test_config_change_history_tracking(self):
        """Test configuration change history tracking."""
        manager = DynamicConfigManager()

        # Make several changes
        await manager.update("setting1", "value1")
        await manager.update("setting1", "value2")
        await manager.update("setting2", "value1")
        await manager.update("setting1", "value3")

        # Check history
        history = manager.get_history()
        assert len(history) == 4

        # Check specific key history
        setting1_history = manager.get_history("setting1")
        assert len(setting1_history) == 3

    @pytest.mark.asyncio
    async def test_service_dependency_ordering(self):
        """Test service startup order respects dependencies."""
        manager = ServiceManager()
        startup_order = []

        async def service_a():
            startup_order.append("a")

        async def service_b():
            startup_order.append("b")

        async def service_c():
            startup_order.append("c")

        manager.register("service_a", service_a)
        manager.register("service_b", service_b, depends_on=["service_a"])
        manager.register("service_c", service_c, depends_on=["service_b"])

        await manager.start_all()

        # Verify order
        assert startup_order.index("a") < startup_order.index("b")
        assert startup_order.index("b") < startup_order.index("c")


class TestPerformance:
    """Performance tests."""

    @pytest.mark.asyncio
    async def test_large_settings_store(self):
        """Test performance with large settings store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SettingsStore(str(Path(tmpdir) / "settings.json"))

            # Add many settings
            for i in range(1000):
                store.set(f"setting_{i}", f"value_{i}")

            # Verify retrieval performance
            import time
            start = time.time()
            for i in range(1000):
                value = store.get(f"setting_{i}")
                assert value == f"value_{i}"
            elapsed = time.time() - start

            # Should complete in reasonable time
            assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_many_health_checks(self):
        """Test performance with many health checks."""
        checker = HealthChecker()

        async def check_service(n):
            return True, f"Service {n} healthy"

        # Register many checks
        for i in range(100):
            checker.register_check(f"service_{i}", lambda n=i: check_service(n))

        import time
        start = time.time()
        status = await checker.check_all()
        elapsed = time.time() - start

        # Should complete quickly even with many checks
        assert elapsed < 2.0
        assert status["status"] == "healthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
