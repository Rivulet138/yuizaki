from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

StorageTarget = Literal["tts_audio", "runtime_temp", "memory"]


class StorageCleanupRequest(BaseModel):
    targets: list[StorageTarget] = Field(min_length=1, max_length=3)
    confirmation: Literal["PERMANENT_CLEAN"]

    model_config = ConfigDict(extra="forbid")


def _walk_regular_files(root: Path) -> tuple[list[Path], int]:
    if not root.is_dir():
        return [], 0
    files: list[Path] = []
    failed = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries: Iterator[os.DirEntry[str]] = os.scandir(directory)
            with entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files.append(Path(entry.path))
                    except OSError:
                        failed += 1
        except OSError:
            failed += 1
    return files, failed


def _directory_snapshot(category_id: str, root: Path) -> dict[str, Any]:
    files, failed = _walk_regular_files(root)
    total_bytes = 0
    for file_path in files:
        try:
            total_bytes += file_path.stat().st_size
        except OSError:
            failed += 1
    return {
        "id": category_id,
        "bytes": total_bytes,
        "files": len(files),
        "action": "delete_files",
        "persistence": "disk",
        "failed_files": failed,
    }


def _resolve_memory_authority(store: Any) -> Any:
    current = store
    visited: set[int] = set()
    while current is not None and hasattr(current, "authority") and id(current) not in visited:
        visited.add(id(current))
        current = current.authority
    return current


def _memory_snapshot(store: Any) -> dict[str, Any]:
    authority = _resolve_memory_authority(store)
    db_path_value = getattr(authority, "db_path", None)
    paths: list[Path] = []
    if db_path_value:
        db_path = Path(db_path_value).expanduser().resolve()
        paths = [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]
    total_bytes = 0
    files = 0
    failed = 0
    for file_path in paths:
        try:
            if file_path.is_file():
                total_bytes += file_path.stat().st_size
                files += 1
        except OSError:
            failed += 1
    return {
        "id": "memory",
        "bytes": total_bytes,
        "files": files,
        "action": "compact" if callable(getattr(authority, "compact_storage", None)) else "none",
        "persistence": "disk" if paths else "memory_only",
        "failed_files": failed,
    }


def _delete_directory_files(root: Path) -> dict[str, int]:
    files, failed = _walk_regular_files(root)
    deleted = 0
    reclaimed = 0
    for file_path in files:
        try:
            file_bytes = file_path.stat().st_size
            file_path.unlink()
            deleted += 1
            reclaimed += file_bytes
        except OSError:
            failed += 1

    directories = sorted(
        {file_path.parent for file_path in files if file_path.parent != root},
        key=lambda value: len(value.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"deleted_files": deleted, "failed_files": failed, "reclaimed_bytes": reclaimed}


class StorageMaintenance:
    def __init__(
        self,
        *,
        audio_cache_dir: Path,
        runtime_temp_dir: Path,
        memory_store_provider: Callable[[], Any],
    ) -> None:
        self.audio_cache_dir = audio_cache_dir.expanduser().resolve()
        self.runtime_temp_dir = runtime_temp_dir.expanduser().resolve()
        self.memory_store_provider = memory_store_provider

    def snapshot(self) -> dict[str, Any]:
        categories = [
            _directory_snapshot("tts_audio", self.audio_cache_dir),
            _directory_snapshot("runtime_temp", self.runtime_temp_dir),
            _memory_snapshot(self.memory_store_provider()),
            {
                "id": "visual_frames",
                "bytes": 0,
                "files": 0,
                "action": "none",
                "persistence": "memory_only",
            },
        ]
        reclaimable_bytes = sum(
            int(category["bytes"])
            for category in categories
            if category["action"] == "delete_files"
        )
        return {
            "categories": categories,
            "total_bytes": sum(int(category["bytes"]) for category in categories),
            "reclaimable_bytes": reclaimable_bytes,
        }

    def cleanup(self, targets: list[StorageTarget]) -> dict[str, Any]:
        result = {"deleted_files": 0, "failed_files": 0, "reclaimed_bytes": 0}
        completed: list[str] = []
        for target in dict.fromkeys(targets):
            if target == "tts_audio":
                target_result = _delete_directory_files(self.audio_cache_dir)
            elif target == "runtime_temp":
                target_result = _delete_directory_files(self.runtime_temp_dir)
            else:
                authority = _resolve_memory_authority(self.memory_store_provider())
                compact = getattr(authority, "compact_storage", None)
                if not callable(compact):
                    target_result = {"deleted_files": 0, "failed_files": 1, "reclaimed_bytes": 0}
                else:
                    compact_result = compact()
                    reclaimed_bytes = int(compact_result.get("reclaimed_bytes", 0)) if isinstance(compact_result, dict) else 0
                    target_result = {
                        "deleted_files": 0,
                        "failed_files": 0,
                        "reclaimed_bytes": reclaimed_bytes,
                    }
            for key in result:
                result[key] += int(target_result[key])
            completed.append(target)
        return {**result, "completed": completed, "status": self.snapshot()}


def create_storage_router(
    *,
    audio_cache_dir: Path,
    runtime_temp_dir: Path,
    memory_store_provider: Callable[[], Any],
    database_provider: Callable[[], Any] | None = None,
) -> APIRouter:
    maintenance = StorageMaintenance(
        audio_cache_dir=audio_cache_dir,
        runtime_temp_dir=runtime_temp_dir,
        memory_store_provider=memory_store_provider,
    )
    router = APIRouter(prefix="/api/system/storage", tags=["storage"])

    async def backup_sources() -> dict[str, Any]:
        from fastapi import HTTPException
        from modules.core.paths import data_dir_from_env, settings_path_from_env

        database = database_provider() if database_provider else None
        database_path = getattr(database, "db_path", None)
        authority = _resolve_memory_authority(memory_store_provider())
        memory_path = getattr(authority, "db_path", None)
        if not database_path:
            raise HTTPException(409, detail="backup_requires_initialized_file_sqlite_database")
        return {
            "source": "running_backend",
            "database": str(Path(database_path).resolve()),
            "memory": str(Path(memory_path).resolve()) if memory_path else str(data_dir_from_env() / "memory.db"),
            "memory_persistence": "disk" if memory_path else "memory_only",
            "settings": str(settings_path_from_env()),
            "data_dir": str(data_dir_from_env()),
            "audio_cache": str(Path(audio_cache_dir).resolve()),
        }

    async def storage_status() -> dict[str, Any]:
        return await asyncio.to_thread(maintenance.snapshot)

    async def cleanup_storage(payload: StorageCleanupRequest) -> dict[str, Any]:
        return await asyncio.to_thread(maintenance.cleanup, payload.targets)

    router.add_api_route("/backup-sources", backup_sources, methods=["GET"])
    router.add_api_route("", storage_status, methods=["GET"])
    router.add_api_route("/cleanup", cleanup_storage, methods=["POST"])
    return router
