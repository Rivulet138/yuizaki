from __future__ import annotations

import hashlib
import http.client
import json
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RESOURCE_LOCK_PATH = Path(__file__).resolve().parents[2] / "resources.lock.json"
PROGRESS_PREFIX = "YUIZAKI_RESOURCE_PROGRESS "


def emit_progress(
    phase: str,
    message: str,
    *,
    bytes_downloaded: int | None = None,
    bytes_total: int | None = None,
) -> None:
    payload: dict[str, Any] = {"phase": phase, "message": message}
    if bytes_downloaded is not None:
        payload["bytesDownloaded"] = max(0, bytes_downloaded)
    if bytes_total is not None and bytes_total >= 0:
        payload["bytesTotal"] = bytes_total
    print(f"{PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=True)}", flush=True)


def _metadata_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.json")


def _read_download_metadata(target: Path, url: str) -> dict[str, Any]:
    metadata_path = _metadata_path(target)
    if not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return payload if payload.get("url") == url else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_download_metadata(target: Path, payload: dict[str, Any]) -> None:
    metadata_path = _metadata_path(target)
    temporary_path = metadata_path.with_name(f"{metadata_path.name}.tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    os.replace(temporary_path, metadata_path)


def remove_download_artifacts(target: Path) -> None:
    target.unlink(missing_ok=True)
    _metadata_path(target).unlink(missing_ok=True)


def _content_range(response: Any) -> tuple[int, int] | None:
    value = str(response.headers.get("Content-Range") or "")
    if not value.startswith("bytes ") or "/" not in value or "-" not in value:
        return None
    try:
        selected, total_text = value[6:].split("/", 1)
        start_text, _ = selected.split("-", 1)
        return int(start_text), int(total_text)
    except ValueError:
        return None


def _unsatisfied_total(error: urllib.error.HTTPError) -> int | None:
    value = str(error.headers.get("Content-Range") or "")
    if not value.startswith("bytes */"):
        return None
    try:
        return int(value[8:])
    except ValueError:
        return None


def download_archive(
    url: str,
    target: Path,
    *,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = _read_download_metadata(target, url)
    if target.exists() and not metadata and _metadata_path(target).exists():
        remove_download_artifacts(target)
    existing_size = target.stat().st_size if target.is_file() else 0
    recorded_total = metadata.get("bytesTotal")
    if existing_size > 0 and isinstance(recorded_total, int) and existing_size == recorded_total:
        emit_progress(
            "downloading",
            "Model archive download complete",
            bytes_downloaded=existing_size,
            bytes_total=recorded_total,
        )
        return

    attempts = max(1, max_retries + 1)
    last_error: BaseException | None = None
    for attempt in range(attempts):
        existing_size = target.stat().st_size if target.is_file() else 0
        headers: dict[str, str] = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
            validator = metadata.get("etag") or metadata.get("lastModified")
            if validator:
                headers["If-Range"] = str(validator)
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - URLs are locked by the caller.
                status = getattr(response, "status", None) or response.getcode()
                range_info = _content_range(response) if status == 206 else None
                can_append = existing_size > 0 and status == 206 and range_info is not None and range_info[0] == existing_size
                if status == 206 and (range_info is None or range_info[0] != existing_size):
                    remove_download_artifacts(target)
                    if existing_size > 0:
                        return download_archive(url, target, max_retries=max_retries, retry_delay=retry_delay)
                    raise ValueError("Server returned an incompatible Content-Range")

                write_mode = "ab" if can_append else "wb"
                downloaded = existing_size if can_append else 0
                content_length = response.headers.get("Content-Length")
                total = range_info[1] if range_info else (int(content_length) + downloaded if content_length else None)
                metadata = {
                    "url": url,
                    "etag": response.headers.get("ETag"),
                    "lastModified": response.headers.get("Last-Modified"),
                    "bytesTotal": total,
                    "updatedAt": datetime.now(UTC).isoformat(),
                }
                _write_download_metadata(target, metadata)
                emit_progress(
                    "downloading",
                    "Resuming model archive" if can_append else "Downloading model archive",
                    bytes_downloaded=downloaded,
                    bytes_total=total,
                )

                last_percent = -1
                with target.open(write_mode) as stream:
                    while True:
                        try:
                            chunk = response.read(1024 * 1024)
                        except http.client.IncompleteRead as error:
                            chunk = error.partial
                            if chunk:
                                stream.write(chunk)
                                downloaded += len(chunk)
                            raise
                        if not chunk:
                            break
                        stream.write(chunk)
                        downloaded += len(chunk)
                        percent = min(100, int(downloaded * 100 / total)) if total else None
                        if percent is not None and percent == last_percent:
                            continue
                        last_percent = percent if percent is not None else last_percent
                        emit_progress(
                            "downloading",
                            "Downloading model archive",
                            bytes_downloaded=downloaded,
                            bytes_total=total,
                        )
                if total is not None and downloaded != total:
                    raise http.client.IncompleteRead(b"", total - downloaded)
                metadata["updatedAt"] = datetime.now(UTC).isoformat()
                _write_download_metadata(target, metadata)
                return
        except urllib.error.HTTPError as error:
            if error.code == 416 and existing_size > 0:
                if _unsatisfied_total(error) == existing_size:
                    metadata["bytesTotal"] = existing_size
                    metadata["updatedAt"] = datetime.now(UTC).isoformat()
                    _write_download_metadata(target, metadata)
                    emit_progress(
                        "downloading",
                        "Model archive download complete",
                        bytes_downloaded=existing_size,
                        bytes_total=existing_size,
                    )
                    return
                remove_download_artifacts(target)
                return download_archive(url, target, max_retries=max_retries, retry_delay=retry_delay)
            last_error = error
        except (urllib.error.URLError, http.client.IncompleteRead, ConnectionError, TimeoutError) as error:
            last_error = error

        if attempt + 1 >= attempts:
            break
        emit_progress("downloading", "Retrying model archive download", bytes_downloaded=target.stat().st_size if target.exists() else 0)
        time.sleep(retry_delay * (2**attempt))

    if last_error is not None:
        raise last_error
    raise RuntimeError("Model archive download failed")


def locked_archive(resource_id: str) -> tuple[str, str]:
    lock = json.loads(RESOURCE_LOCK_PATH.read_text(encoding="utf-8"))
    source = lock["resources"][resource_id]["sources"][0]
    return str(source["url"]), str(source["sha256"])


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.strip().lower():
        raise ValueError(f"SHA256 mismatch for {path.name}: expected {expected}, got {actual}")


def safe_extract(archive: tarfile.TarFile, target: Path) -> None:
    target = target.resolve()
    for member in archive.getmembers():
        destination = (target / member.name).resolve()
        if not destination.is_relative_to(target):
            raise ValueError(f"Archive member escapes target directory: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"Archive links are not allowed: {member.name}")
    if sys.version_info >= (3, 12):
        archive.extractall(target, filter="data")
    else:
        archive.extractall(target)
