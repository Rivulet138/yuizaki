from __future__ import annotations

import argparse
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


DEFAULT_ASSET_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2025-01-06.tar.bz2"
)


def find_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if not matches:
        raise FileNotFoundError(f"Could not find {name} inside {root}")
    matches.sort(key=lambda item: len(item.parts))
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download sherpa-onnx SenseVoice assets into the Yuizaki cache.")
    parser.add_argument("--asset-url", default=DEFAULT_ASSET_URL)
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "sherpa-onnx" / "sensevoice",
    )
    args = parser.parse_args()

    target_dir = args.target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="yuizaki-sherpa-") as tmpdir:
        archive_path = Path(tmpdir) / "sherpa-sensevoice.tar.bz2"
        print(f"Downloading {args.asset_url}")
        urllib.request.urlretrieve(args.asset_url, archive_path)

        extract_root = Path(tmpdir) / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:bz2") as tar:
            tar.extractall(extract_root)

        model_path = find_file(extract_root, "model.int8.onnx")
        tokens_path = find_file(extract_root, "tokens.txt")

        shutil.copyfile(model_path, target_dir / "model.int8.onnx")
        shutil.copyfile(tokens_path, target_dir / "tokens.txt")

    print(f"Sherpa SenseVoice assets ready in {target_dir}")


if __name__ == "__main__":
    main()
