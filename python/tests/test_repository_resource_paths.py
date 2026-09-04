from pathlib import Path

from modules.core.paths import BACKEND_ROOT, resolve_optional_backend_path
from modules.core.config import normalize_genie_model_dir
from modules.tts.synthesizer import TTSClient


def test_optional_backend_path_resolves_repository_relative_resource() -> None:
    resolved = resolve_optional_backend_path("CharacterModels/v2ProPlus/feibi/tts_models")

    assert resolved == (BACKEND_ROOT / "CharacterModels" / "v2ProPlus" / "feibi" / "tts_models").resolve()


def test_optional_backend_path_preserves_absolute_resource(tmp_path: Path) -> None:
    resource = tmp_path / "voice.onnx"

    assert resolve_optional_backend_path(resource) == resource.resolve()


def test_genie_client_resolves_model_and_reference_paths_inside_repository() -> None:
    client = TTSClient(
        genie_model_dir="CharacterModels/v2ProPlus/feibi/tts_models",
        ref_audio="CharacterModels/v2ProPlus/feibi/prompt_wav/normal.wav",
        ref_text="reference",
    )

    assert client._model_dir == str(
        (BACKEND_ROOT / "CharacterModels" / "v2ProPlus" / "feibi" / "tts_models").resolve()
    )
    assert client._ref_audio == str(
        (BACKEND_ROOT / "CharacterModels" / "v2ProPlus" / "feibi" / "prompt_wav" / "normal.wav").resolve()
    )


def test_legacy_default_genie_model_path_uses_builtin_mode() -> None:
    assert normalize_genie_model_dir(
        "CharacterModels\\v2ProPlus\\普拉琪娜_e15_e8_correct_sampling_v2"
    ) == ""
