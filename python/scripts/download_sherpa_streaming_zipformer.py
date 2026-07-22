from __future__ import annotations

import argparse
import json
import os
import shutil
import tarfile
from pathlib import Path

try:
    from .resource_archive import download_archive, emit_progress, locked_archive, remove_download_artifacts, safe_extract, verify_sha256
except ImportError:
    from resource_archive import download_archive, emit_progress, locked_archive, remove_download_artifacts, safe_extract, verify_sha256


DEFAULT_ASSET_URL, DEFAULT_SHA256 = locked_archive("sherpa_online")
VALIDATION_FILENAME = ".yuizaki-validation.json"


def find_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if not matches:
        raise FileNotFoundError(f"Could not find {name} inside {root}")
    matches.sort(key=lambda item: len(item.parts))
    return matches[0]


def validate_model(model_path: Path, tokens_path: Path) -> None:
    import sherpa_onnx  # type: ignore[import-untyped]

    recognizer = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
        model=str(model_path),
        tokens=str(tokens_path),
        num_threads=1,
        provider="cpu",
        enable_endpoint_detection=False,
    )
    recognizer.create_stream()


def validation_payload(model_path: Path, tokens_path: Path, asset_url: str) -> dict[str, object]:
    model_stat = model_path.stat()
    tokens_stat = tokens_path.stat()
    return {
        "format": "sherpa-onnx-online-zipformer2-ctc",
        "source": asset_url,
        "model": {
            "name": model_path.name,
            "size": model_stat.st_size,
            "mtime_ns": str(model_stat.st_mtime_ns),
        },
        "tokens": {
            "name": tokens_path.name,
            "size": tokens_stat.st_size,
            "mtime_ns": str(tokens_stat.st_mtime_ns),
        },
    }


def write_validation_manifest(target_dir: Path, payload: dict[str, object]) -> None:
    manifest_path = target_dir / VALIDATION_FILENAME
    temporary_path = manifest_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    os.replace(temporary_path, manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and validate Yuizaki's sherpa-onnx streaming ASR model.")
    parser.add_argument("--asset-url", default=DEFAULT_ASSET_URL)
    parser.add_argument("--sha256", default=DEFAULT_SHA256)
    parser.add_argument("--archive-path", type=Path, help="Use an existing archive instead of downloading it.")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "sherpa-onnx" / "streaming-zipformer-small-ctc-zh",
    )
    args = parser.parse_args()

    target_dir = args.target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    download_dir = target_dir / ".download"
    downloaded_archive = not args.archive_path
    archive_path = args.archive_path.resolve() if args.archive_path else download_dir / "sherpa-streaming.tar.bz2.part"
    if args.archive_path and not archive_path.is_file():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    if args.archive_path:
        print(f"Using existing archive {archive_path}")
    extract_root = download_dir / "extract"
    shutil.rmtree(extract_root, ignore_errors=True)
    try:
        if downloaded_archive:
            download_archive(args.asset_url, archive_path)
        emit_progress("verifying", "Verifying model archive")
        try:
            verify_sha256(archive_path, args.sha256)
        except ValueError:
            if downloaded_archive:
                remove_download_artifacts(archive_path)
            raise

        emit_progress("extracting", "Extracting model archive")
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:bz2") as archive:
            safe_extract(archive, extract_root)

        source_model = find_file(extract_root, "model.int8.onnx")
        source_tokens = find_file(extract_root, "tokens.txt")
        model_path = target_dir / "model.int8.onnx"
        tokens_path = target_dir / "tokens.txt"
        staging_dir = target_dir / ".staging"
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True)
        staged_model = staging_dir / "model.int8.onnx"
        staged_tokens = staging_dir / "tokens.txt"
        try:
            emit_progress("installing", "Validating and installing model files")
            shutil.copyfile(source_model, staged_model)
            shutil.copyfile(source_tokens, staged_tokens)
            validate_model(staged_model, staged_tokens)
            os.replace(staged_model, model_path)
            os.replace(staged_tokens, tokens_path)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
        write_validation_manifest(target_dir, validation_payload(model_path, tokens_path, args.asset_url))
        if downloaded_archive:
            remove_download_artifacts(archive_path)
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)
        if download_dir.exists() and not any(download_dir.iterdir()):
            download_dir.rmdir()

    print(f"Sherpa streaming Zipformer2 CTC assets validated in {target_dir}")


if __name__ == "__main__":
    main()
