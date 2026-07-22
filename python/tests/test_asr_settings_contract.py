import pytest
from pydantic import ValidationError

from modules.system.settings_schema import ASRSettingsModel, ASRSettingsPatchModel


def test_asr_settings_default_endpoint_matches_runtime_contract():
    assert ASRSettingsModel().provider == "sherpa-onnx-online"
    assert ASRSettingsModel().vad_min_silence_ms == 300


def test_asr_settings_normalize_endpoint_and_partial_ranges():
    settings = ASRSettingsModel(
        vad_threshold=2,
        vad_min_silence_ms=5000,
        asr_partial_every=0,
    )

    assert settings.vad_threshold == 0.9
    assert settings.vad_min_silence_ms == 1200
    assert settings.asr_partial_every == 1


def test_asr_patch_rejects_removed_whisper_fields():
    with pytest.raises(ValidationError):
        ASRSettingsPatchModel(whisper_model="small")


def test_asr_patch_normalizes_active_controls():
    patch = ASRSettingsPatchModel(vad_threshold=0, vad_min_silence_ms=100, asr_partial_every=99)

    payload = patch.model_dump(exclude_none=True)
    assert set(payload) == {"vad_threshold", "vad_min_silence_ms", "asr_partial_every"}
    assert patch.vad_threshold == 0.1
    assert patch.vad_min_silence_ms == 160
    assert patch.asr_partial_every == 30


def test_asr_settings_accept_only_sherpa_runtime_providers():
    for provider in ("cpu", "cuda", "coreml"):
        assert ASRSettingsPatchModel(sherpa_provider=provider).sherpa_provider == provider

    with pytest.raises(ValidationError):
        ASRSettingsPatchModel(sherpa_provider="directml")
