from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.storage_api import create_storage_router


class _MemoryStore:
    backend_name = "sqlite"

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.compactions = 0

    def compact_storage(self) -> dict[str, int | str]:
        self.compactions += 1
        return {
            "backend": self.backend_name,
            "before_bytes": self.db_path.stat().st_size,
            "after_bytes": self.db_path.stat().st_size,
            "reclaimed_bytes": 0,
        }


def _build_client(tmp_path: Path) -> tuple[TestClient, Path, Path, _MemoryStore]:
    audio_cache = tmp_path / "audio"
    runtime_temp = tmp_path / "tmp"
    memory_db = tmp_path / "memory.db"
    audio_cache.mkdir()
    runtime_temp.mkdir()
    memory_db.write_bytes(b"memory")
    store = _MemoryStore(memory_db)
    app = FastAPI()
    app.include_router(
        create_storage_router(
            audio_cache_dir=audio_cache,
            runtime_temp_dir=runtime_temp,
            memory_store_provider=lambda: store,
        )
    )
    return TestClient(app), audio_cache, runtime_temp, store


def test_storage_status_reports_only_canonical_categories(tmp_path: Path) -> None:
    client, audio_cache, runtime_temp, _store = _build_client(tmp_path)
    (audio_cache / "reply.wav").write_bytes(b"1234")
    (runtime_temp / "vision.bin").write_bytes(b"12")

    response = client.get("/api/system/storage")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["categories"]] == [
        "tts_audio",
        "runtime_temp",
        "memory",
        "visual_frames",
    ]
    assert payload["reclaimable_bytes"] == 6
    assert payload["categories"][3] == {
        "id": "visual_frames",
        "bytes": 0,
        "files": 0,
        "action": "none",
        "persistence": "memory_only",
    }


def test_storage_cleanup_requires_exact_confirmation(tmp_path: Path) -> None:
    client, audio_cache, _runtime_temp, _store = _build_client(tmp_path)
    target = audio_cache / "reply.wav"
    target.write_bytes(b"audio")

    response = client.post(
        "/api/system/storage/cleanup",
        json={"targets": ["tts_audio"], "confirmation": "DELETE"},
    )

    assert response.status_code == 422
    assert target.exists()


def test_storage_cleanup_permanently_deletes_cache_and_compacts_memory(tmp_path: Path) -> None:
    client, audio_cache, runtime_temp, store = _build_client(tmp_path)
    audio_file = audio_cache / "reply.wav"
    temp_file = runtime_temp / "nested" / "frame.bin"
    temp_file.parent.mkdir()
    audio_file.write_bytes(b"audio")
    temp_file.write_bytes(b"frame")

    response = client.post(
        "/api/system/storage/cleanup",
        json={
            "targets": ["tts_audio", "runtime_temp", "memory"],
            "confirmation": "PERMANENT_CLEAN",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_files"] == 2
    assert payload["failed_files"] == 0
    assert payload["reclaimed_bytes"] == 10
    assert store.compactions == 1
    assert not audio_file.exists()
    assert not temp_file.exists()

