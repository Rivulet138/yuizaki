from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prefetch_embedding_model import fetch_embedding_snapshot
from scripts.prefetch_genie_tts import GENIE_REPO_ID, prefetch_genie_assets, validate_character_name


def test_genie_prefetch_uses_locked_shared_and_character_paths(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def snapshot_download(**kwargs: object) -> str:
        calls.append(kwargs)
        return str(kwargs["local_dir"])

    genie_data_dir = tmp_path / "cache" / "GenieData" / "GenieData"
    workspace_root = tmp_path / "python"
    data_dir, character_dir = prefetch_genie_assets(
        character="feibi",
        revision="a" * 40,
        genie_data_dir=genie_data_dir,
        workspace_root=workspace_root,
        include_predefined_character=True,
        max_workers=3,
        snapshot_download_fn=snapshot_download,
    )

    assert data_dir == genie_data_dir
    assert character_dir == workspace_root / "CharacterModels" / "v2ProPlus" / "feibi"
    assert calls == [
        {
            "repo_id": GENIE_REPO_ID,
            "revision": "a" * 40,
            "allow_patterns": "GenieData/*",
            "local_dir": str(genie_data_dir.parent),
            "max_workers": 3,
        },
        {
            "repo_id": GENIE_REPO_ID,
            "revision": "a" * 40,
            "allow_patterns": "CharacterModels/v2ProPlus/feibi/*",
            "local_dir": str(workspace_root),
            "max_workers": 3,
        },
    ]


def test_genie_custom_model_skips_predefined_character_download(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    prefetch_genie_assets(
        character="角色_01",
        revision="b" * 40,
        genie_data_dir=tmp_path / "GenieData" / "GenieData",
        workspace_root=tmp_path,
        include_predefined_character=False,
        max_workers=1,
        snapshot_download_fn=lambda **kwargs: calls.append(kwargs) or str(tmp_path),
    )

    assert len(calls) == 1
    assert calls[0]["allow_patterns"] == "GenieData/*"


@pytest.mark.parametrize("character", ["../feibi", "folder/feibi", "folder\\feibi", ".", ""])
def test_genie_character_name_rejects_path_escape(character: str) -> None:
    with pytest.raises(ValueError):
        validate_character_name(character)


def test_embedding_prefetch_passes_revision_to_hugging_face(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    snapshot = tmp_path / "snapshot"

    result = fetch_embedding_snapshot(
        "Qwen/Qwen3-Embedding-0.6B",
        "c" * 40,
        tmp_path / "cache",
        2,
        lambda **kwargs: calls.append(kwargs) or str(snapshot),
    )

    assert result == snapshot.resolve()
    assert calls == [{
        "repo_id": "Qwen/Qwen3-Embedding-0.6B",
        "revision": "c" * 40,
        "cache_dir": str(tmp_path / "cache"),
        "max_workers": 2,
    }]


def test_embedding_prefetch_accepts_existing_local_model(tmp_path: Path) -> None:
    local_model = tmp_path / "local-model"
    local_model.mkdir()

    result = fetch_embedding_snapshot(
        str(local_model),
        None,
        tmp_path / "cache",
        2,
        lambda **_kwargs: pytest.fail("local models must not use Hugging Face"),
    )

    assert result == local_model.resolve()
