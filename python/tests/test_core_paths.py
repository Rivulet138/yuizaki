from __future__ import annotations

from modules.agent.agent_trace_store import AgentTraceStore
from modules.agent.mcp_manager import MCPManager
from modules.agent.policy_engine import PolicyEngine
from modules.agent.schedule_store import ScheduleStore
from modules.agent.skill_store import SkillCatalogStore
from modules.agent_plugins.manager import PluginManager
from modules.core.config import AppConfig, LLMConfig, public_config_snapshot
from modules.core.paths import BACKEND_ROOT, DEFAULT_AUDIO_CACHE_DIR, audio_cache_dir_from_env


def test_audio_cache_path_uses_canonical_variable_and_backend_relative_paths(monkeypatch) -> None:
    monkeypatch.setenv("AUDIO_CACHE_DIR", "runtime-audio")

    expected = (BACKEND_ROOT / "runtime-audio").resolve()
    assert audio_cache_dir_from_env() == expected


def test_audio_cache_path_ignores_removed_legacy_variable(monkeypatch) -> None:
    monkeypatch.delenv("AUDIO_CACHE_DIR", raising=False)
    monkeypatch.setenv("TTS_AUDIO_CACHE_DIR", "legacy-audio")

    assert audio_cache_dir_from_env() == DEFAULT_AUDIO_CACHE_DIR


def test_runtime_stores_share_configured_data_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(tmp_path))

    assert AgentTraceStore().path == tmp_path / "agent_trace.json"
    assert MCPManager()._store_file == tmp_path / "mcp_servers.json"
    assert PolicyEngine()._store_file == tmp_path / "permissions.json"
    assert ScheduleStore().path == tmp_path / "schedules.json"
    assert SkillCatalogStore().path == tmp_path / "imported_skills.json"
    assert PluginManager()._store_file == tmp_path / "agent_plugins.json"


def test_public_system_config_does_not_expose_llm_api_key(monkeypatch) -> None:
    payload = public_config_snapshot(AppConfig(llm=LLMConfig(api_key="secret-value")))

    assert "api_key" not in payload["llm"]
    assert payload["llm"]["api_key_configured"] is True
    assert payload["llm"]["model"] == ""
