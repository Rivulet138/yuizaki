from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path

try:
    from .resource_archive import download_archive, emit_progress, locked_archive, remove_download_artifacts, safe_extract, verify_sha256
except ImportError:
    from resource_archive import download_archive, emit_progress, locked_archive, remove_download_artifacts, safe_extract, verify_sha256


DEFAULT_ASSET_URL, DEFAULT_SHA256 = locked_archive("sherpa")


def find_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if not matches:
        raise FileNotFoundError(f"Could not find {name} inside {root}")
    matches.sort(key=lambda item: len(item.parts))
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download sherpa-onnx SenseVoice assets into the Yuizaki cache.")
    parser.add_argument("--asset-url", default=DEFAULT_ASSET_URL)
    parser.add_argument("--sha256", default=DEFAULT_SHA256)
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "sherpa-onnx" / "sensevoice",
    )
    args = parser.parse_args()

    target_dir = args.target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    download_dir = target_dir / ".download"
    archive_path = download_dir / "sherpa-sensevoice.tar.bz2.part"
    extract_root = download_dir / "extract"
    shutil.rmtree(extract_root, ignore_errors=True)
    try:
        download_archive(args.asset_url, archive_path)
        emit_progress("verifying", "Verifying model archive")
        try:
            verify_sha256(archive_path, args.sha256)
        except ValueError:
            remove_download_artifacts(archive_path)
            raise

        emit_progress("extracting", "Extracting model archive")
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:bz2") as tar:
            safe_extract(tar, extract_root)

        model_path = find_file(extract_root, "model.int8.onnx")
        tokens_path = find_file(extract_root, "tokens.txt")

        emit_progress("installing", "Installing model files")
        shutil.copyfile(model_path, target_dir / "model.int8.onnx")
        shutil.copyfile(tokens_path, target_dir / "tokens.txt")
        remove_download_artifacts(archive_path)
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)
        if download_dir.exists() and not any(download_dir.iterdir()):
            download_dir.rmdir()

    print(f"Sherpa SenseVoice assets ready in {target_dir}")


if __name__ == "__main__":
    main()
