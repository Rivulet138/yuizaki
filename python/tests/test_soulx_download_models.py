from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def test_soulx_cli_paths_and_revisions_are_forwarded(monkeypatch, tmp_path: Path) -> None:
    lock_path = tmp_path / "resources.lock.json"
    lock_path.write_text(
        json.dumps({"resources": {"soulx": {"sources": [{"revision": "singer-test"}, {"revision": "pre-test"}]}}}),
        encoding="utf-8",
    )
    models_dir = tmp_path / "models"
    references_dir = tmp_path / "references"
    calls: list[tuple[str, Path, str]] = []

    spec = importlib.util.spec_from_file_location("soulx_test", Path(__file__).parents[2] / "services/soulx-svc/download_models.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "hf_hub_download", lambda **kwargs: calls.append(("checkpoint", Path(kwargs["local_dir"]), kwargs["revision"])) or str(Path(kwargs["local_dir"]) / "model.pt"))
    monkeypatch.setattr(module, "snapshot_download", lambda **kwargs: calls.append((kwargs["repo_id"], Path(kwargs["local_dir"]), kwargs["revision"])))
    monkeypatch.setattr(sys, "argv", ["download_models.py", "--models-dir", str(models_dir), "--references-dir", str(references_dir), "--lock-path", str(lock_path)])
    module.main()

    assert calls == [
        ("checkpoint", models_dir / "SoulX-Singer", "singer-test"),
        ("Soul-AILab/SoulX-Singer-Preprocess", models_dir / "SoulX-Singer-Preprocess", "pre-test"),
    ]
    assert references_dir.exists()
