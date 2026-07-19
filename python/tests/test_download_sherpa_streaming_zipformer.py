from __future__ import annotations

import io
import json
import tarfile

import pytest

from scripts.download_sherpa_streaming_zipformer import (
    VALIDATION_FILENAME,
    safe_extract,
    validation_payload,
    write_validation_manifest,
)


def test_validation_manifest_tracks_exact_files(tmp_path):
    model_path = tmp_path / "model.int8.onnx"
    tokens_path = tmp_path / "tokens.txt"
    model_path.write_bytes(b"online-model")
    tokens_path.write_text("tokens", encoding="utf-8")

    payload = validation_payload(model_path, tokens_path, "https://example.invalid/model.tar.bz2")
    write_validation_manifest(tmp_path, payload)

    stored = json.loads((tmp_path / VALIDATION_FILENAME).read_text(encoding="utf-8"))
    assert stored["format"] == "sherpa-onnx-online-zipformer2-ctc"
    assert stored["model"]["size"] == model_path.stat().st_size
    assert stored["model"]["mtime_ns"] == str(model_path.stat().st_mtime_ns)


def test_safe_extract_rejects_parent_directory_escape(tmp_path):
    archive_path = tmp_path / "unsafe.tar"
    with tarfile.open(archive_path, "w") as archive:
        content = b"escape"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    with tarfile.open(archive_path, "r") as archive:
        with pytest.raises(ValueError, match="escapes target directory"):
            safe_extract(archive, tmp_path / "extract")

    assert not (tmp_path / "escape.txt").exists()
