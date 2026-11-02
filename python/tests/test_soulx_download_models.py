from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from huggingface_hub.errors import EntryNotFoundError


@pytest.fixture
def download_models() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "soulx_test", Path(__file__).parents[2] / "services/soulx-svc/download_models.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_soulx_cli_paths_and_revisions_are_forwarded(monkeypatch, tmp_path: Path, download_models: ModuleType) -> None:
    lock_path = tmp_path / "resources.lock.json"
    lock_path.write_text(
        json.dumps({"resources": {"soulx": {"sources": [{"revision": "singer-test"}, {"revision": "pre-test"}]}}}),
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    references_dir = tmp_path / "references"
    calls: list[tuple[str, Path, str]] = []

    def fake_hf_hub_download(*, repo_id: str, filename: str, repo_type: str, revision: str, local_dir: str) -> str:
        assert repo_id == "Soul-AILab/SoulX-Singer"
        assert filename == "model-svc.pt"
        assert repo_type == "model"
        assert Path(local_dir).is_dir()
        calls.append(("checkpoint", Path(local_dir), revision))
        return str(Path(local_dir) / filename)

    def fake_snapshot_download(*, repo_id: str, repo_type: str, revision: str, local_dir: str) -> str:
        assert repo_type == "model"
        assert Path(local_dir).is_dir()
        calls.append((repo_id, Path(local_dir), revision))
        return local_dir

    monkeypatch.setattr(download_models, "hf_hub_download", fake_hf_hub_download)
    monkeypatch.setattr(download_models, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(sys, "argv", ["download_models.py", "--models-dir", str(models_dir), "--references-dir", str(references_dir), "--lock-path", str(lock_path)])
    download_models.main()

    assert calls == [
        ("checkpoint", models_dir / "SoulX-Singer", "singer-test"),
        ("Soul-AILab/SoulX-Singer-Preprocess", models_dir / "SoulX-Singer-Preprocess", "pre-test"),
    ]
    assert references_dir.exists()


@pytest.mark.parametrize("available_filename", ["model-svc.pt", "model.pt", None])
def test_soulx_checkpoint_fallback(
    monkeypatch, tmp_path: Path, download_models: ModuleType, available_filename: str | None
) -> None:
    local_dir = tmp_path / "SoulX-Singer"
    attempted_filenames: list[str] = []

    def fake_hf_hub_download(*, repo_id: str, filename: str, repo_type: str, revision: str, local_dir: str) -> str:
        assert repo_id == "Soul-AILab/SoulX-Singer"
        assert repo_type == "model"
        assert revision == "singer-test"
        assert Path(local_dir) == tmp_path / "SoulX-Singer"
        assert Path(local_dir).is_dir()
        attempted_filenames.append(filename)
        if filename != available_filename:
            raise EntryNotFoundError(filename)
        return str(Path(local_dir) / filename)

    monkeypatch.setattr(download_models, "hf_hub_download", fake_hf_hub_download)

    if available_filename is None:
        with pytest.raises(FileNotFoundError, match="Neither model-svc.pt nor model.pt"):
            download_models.download_soulx_checkpoint(local_dir, "singer-test")
    else:
        assert download_models.download_soulx_checkpoint(local_dir, "singer-test") == local_dir / available_filename

    assert attempted_filenames == (["model-svc.pt"] if available_filename == "model-svc.pt" else ["model-svc.pt", "model.pt"])


def test_soulx_checkpoint_does_not_fallback_on_other_errors(monkeypatch, tmp_path: Path, download_models: ModuleType) -> None:
    attempted_filenames: list[str] = []
    error = RuntimeError("download failed")

    def fake_hf_hub_download(*, repo_id: str, filename: str, repo_type: str, revision: str, local_dir: str) -> str:
        attempted_filenames.append(filename)
        raise error

    monkeypatch.setattr(download_models, "hf_hub_download", fake_hf_hub_download)

    with pytest.raises(RuntimeError) as exc_info:
        download_models.download_soulx_checkpoint(tmp_path / "SoulX-Singer", "singer-test")

    assert exc_info.value is error
    assert attempted_filenames == ["model-svc.pt"]
