from __future__ import annotations

from types import SimpleNamespace

from modules.system.settings_api import SettingsAPI
from modules.system.runtime_config import apply_runtime_config
from modules.system.settings_schema import SummarySettingsPatchModel, SummarySettingsModel


def test_vision_timeout_change_marks_llm_runtime_for_reload() -> None:
    config = SimpleNamespace(
        llm=SimpleNamespace(
            provider="custom",
            base_url="https://example.test/v1",
            api_key="",
            model="vision-model",
            timeout=60.0,
            context_max_tokens=8192,
            default_max_output_tokens=1024,
            temperature=1.0,
            top_p=1.0,
            top_k=40,
            min_p=0.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            repetition_penalty=1.0,
            vision_enabled=True,
            vision_provider="custom",
            vision_base_url="https://vision.example.test/v1",
            vision_api_key="",
            vision_model="vision-model",
            vision_timeout=30.0,
            vision_detail="low",
        ),
    )

    changed = apply_runtime_config(config, {"llm": {"vision_timeout": 45}})

    assert config.llm.vision_timeout == 45.0
    assert changed == {"llm"}


def test_memory_reranker_changes_require_backend_reload() -> None:
    api = SettingsAPI.__new__(SettingsAPI)

    sections = api._runtime_reload_sections(
        {"memory": {"reranker_enabled": True}},
        {"memory"},
    )

    assert sections == {"memory"}


def test_summary_limits_match_runtime_minimums() -> None:
    patch = SummarySettingsPatchModel(
        trigger_messages=0,
        keep_recent_messages=0,
        item_max_chars=0,
        rewrite_interval_messages=0,
        quality_score_cooldown_seconds=0,
        quality_score_budget_per_hour=0,
    )
    assert patch.model_dump() == {
        "trigger_messages": 1,
        "keep_recent_messages": 1,
        "item_max_chars": 20,
        "rewrite_interval_messages": 1,
        "quality_scorer_mode": None,
        "quality_score_cooldown_seconds": 1,
        "quality_score_budget_per_hour": 1,
    }

    settings = SummarySettingsModel(
        trigger_messages=0,
        keep_recent_messages=0,
        item_max_chars=0,
        rewrite_interval_messages=0,
        quality_score_cooldown_seconds=0,
        quality_score_budget_per_hour=0,
    )
    assert settings.item_max_chars == 20
    assert settings.keep_recent_messages == 1
