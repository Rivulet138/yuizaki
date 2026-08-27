from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.memory.backend import MemoryBackendStatus
from modules.memory.routes import MemoryState, create_memory_router
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document


class MemoryIndexRebuildCancelled(RuntimeError):
    pass


class _RebuildStore:
    backend_name = "test-index"

    def __init__(self, *, fail_attempts: int = 0) -> None:
        self.documents = [
            Document(id="one", text="first", metadata={}),
            Document(id="two", text="second", metadata={}),
        ]
        self.fail_attempts = fail_attempts
        self.attempts = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def list_documents(self) -> list[Document]:
        return list(self.documents)

    def get_status(self) -> MemoryBackendStatus:
        return MemoryBackendStatus(
            backend=self.backend_name,
            healthy=True,
            message="authority remains available",
            document_count=len(self.documents),
            metadata={"index_healthy": False, "index_dirty": True},
        )

    def rebuild_index(
        self,
        *,
        progress_callback: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        self.attempts += 1
        if progress_callback:
            progress_callback(1, len(self.documents), "indexing")
        self.started.set()
        while not self.release.wait(0.005):
            if should_cancel and should_cancel():
                raise MemoryIndexRebuildCancelled()
        if self.attempts <= self.fail_attempts:
            raise RuntimeError("simulated rebuild failure")
        if progress_callback:
            progress_callback(len(self.documents), len(self.documents), "finalizing")
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "document_count": len(self.documents),
            "indexed_count": len(self.documents),
            "skipped_count": 0,
        }


class _CheckpointRebuildStore(_RebuildStore):
    def __init__(self) -> None:
        super().__init__(fail_attempts=1)
        self.snapshot_revision = 7
        self.embedding_config_revision = "embedding-v1"
        self.received: list[dict[str, Any]] = []
        self.release.set()

    def get_rebuild_checkpoint_context(self) -> dict[str, Any]:
        return {
            "snapshot_revision": self.snapshot_revision,
            "embedding_config_revision": self.embedding_config_revision,
            "durable_resume": True,
        }

    def mark_index_dirty(self) -> None:
        return None

    def rebuild_index(
        self,
        *,
        progress_callback: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        checkpoint_callback: Callable[[str, int, int, str], None] | None = None,
        snapshot_revision: int | None = None,
        index_generation: str | None = None,
        cursor_key: str | None = None,
        embedding_config_revision: str | None = None,
        processed_count: int = 0,
    ) -> dict[str, Any]:
        self.received.append({
            "snapshot_revision": snapshot_revision,
            "index_generation": index_generation,
            "cursor_key": cursor_key,
            "embedding_config_revision": embedding_config_revision,
            "processed_count": processed_count,
        })
        self.attempts += 1
        if checkpoint_callback is not None and cursor_key is None:
            checkpoint_callback("one", 1, len(self.documents), "indexing")
        if self.attempts <= self.fail_attempts:
            raise RuntimeError("simulated checkpoint failure")
        if progress_callback is not None:
            progress_callback(len(self.documents), len(self.documents), "complete")
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "document_count": len(self.documents),
            "indexed_count": len(self.documents),
            "skipped_count": 0,
        }


def _client(store: _RebuildStore) -> TestClient:
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=store)))
    return TestClient(app)


def _wait_for_job(client: TestClient, job_id: str, expected: str) -> dict[str, Any]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get(f"/memory/index/rebuild/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["job"]["state"] == expected:
            return payload["job"]
        time.sleep(0.01)
    raise AssertionError(f"rebuild job {job_id} did not reach {expected}")


def test_rebuild_job_reports_progress_cancels_and_retries_without_blocking_status() -> None:
    store = _RebuildStore()
    with _client(store) as client:
        started = client.post("/memory/index/rebuild")
        assert started.status_code == 200
        job_id = started.json()["job"]["job_id"]
        assert store.started.wait(1)

        status = client.get("/memory/index/status")
        assert status.status_code == 200
        assert status.json()["status"] == "indexing"
        assert status.json()["job"]["processed_count"] == 1
        assert status.json()["message"] == "authority remains available"

        cancelling = client.post(f"/memory/index/rebuild/{job_id}/cancel")
        assert cancelling.status_code == 200
        assert cancelling.json()["status"] == "cancelling"
        cancelled = _wait_for_job(client, job_id, "cancelled")
        assert cancelled["recoverable"] is True

        store.release.set()
        retried = client.post(f"/memory/index/rebuild/{job_id}/retry")
        assert retried.status_code == 200
        retry_job_id = retried.json()["job"]["job_id"]
        assert retry_job_id != job_id
        completed = _wait_for_job(client, retry_job_id, "completed")
        assert completed["retry_of"] == job_id
        assert completed["processed_count"] == 2


def test_failed_rebuild_is_recoverable_and_retry_reaches_completed() -> None:
    store = _RebuildStore(fail_attempts=1)
    store.release.set()
    with _client(store) as client:
        started = client.post("/memory/index/rebuild").json()
        failed = _wait_for_job(client, started["job"]["job_id"], "failed")
        assert failed["last_error"] == "simulated rebuild failure"
        assert failed["recoverable"] is True

        retried = client.post(f"/memory/index/rebuild/{failed['job_id']}/retry")
        assert retried.status_code == 200
        completed = _wait_for_job(client, retried.json()["job"]["job_id"], "completed")
        assert completed["result"]["status"] == "rebuilt"


def test_duplicate_rebuild_requests_share_one_background_job() -> None:
    store = _RebuildStore()
    with _client(store) as client:
        first = client.post("/memory/index/rebuild").json()
        second = client.post("/memory/index/rebuild").json()
        assert second["job"]["job_id"] == first["job"]["job_id"]
        assert store.started.wait(1)
        store.release.set()
        _wait_for_job(client, first["job"]["job_id"], "completed")
        assert store.attempts == 1


def test_sqlite_journal_restores_abandoned_job_as_recoverable_after_restart(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    first_store = SQLiteMemoryStore(db_path)
    first_store.persist_rebuild_job({
        "job_id": "abandoned-job",
        "state": "running",
        "phase": "indexing",
        "total_count": 10,
        "processed_count": 4,
        "started_at": "2026-08-27T00:00:00+00:00",
        "updated_at": "2026-08-27T00:00:01+00:00",
        "finished_at": None,
        "last_error": None,
        "recoverable": False,
        "retry_of": None,
        "result": None,
    })

    restarted_store = SQLiteMemoryStore(db_path)
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=restarted_store)))
    with TestClient(app) as client:
        status = client.get("/memory/index/status")
        assert status.status_code == 200
        restored = status.json()["job"]
        assert restored["job_id"] == "abandoned-job"
        assert restored["state"] == "interrupted"
        assert restored["processed_count"] == 4
        assert restored["recoverable"] is True
        assert "restarted" in restored["last_error"]

        persisted = restarted_store.load_latest_rebuild_job()
        assert persisted is not None
        assert persisted["state"] == "interrupted"

        retried = client.post("/memory/index/rebuild/abandoned-job/retry")
        assert retried.status_code == 200
        retry_job_id = retried.json()["job"]["job_id"]
        completed = _wait_for_job(client, retry_job_id, "completed")
        assert completed["retry_of"] == "abandoned-job"


def test_durable_retry_reuses_generation_and_cursor_when_checkpoint_matches() -> None:
    store = _CheckpointRebuildStore()
    with _client(store) as client:
        first = client.post("/memory/index/rebuild").json()["job"]
        failed = _wait_for_job(client, first["job_id"], "failed")
        assert failed["cursor_key"] == "one"
        assert failed["processed_count"] == 1

        retried = client.post(f"/memory/index/rebuild/{first['job_id']}/retry").json()["job"]
        completed = _wait_for_job(client, retried["job_id"], "completed")

    assert completed["index_generation"] == first["index_generation"]
    assert store.received[1]["cursor_key"] == "one"
    assert store.received[1]["processed_count"] == 1


@pytest.mark.parametrize("changed_field", ["snapshot_revision", "embedding_config_revision"])
def test_retry_resets_checkpoint_when_authority_or_embedding_config_changes(
    changed_field: str,
) -> None:
    store = _CheckpointRebuildStore()
    with _client(store) as client:
        first = client.post("/memory/index/rebuild").json()["job"]
        _wait_for_job(client, first["job_id"], "failed")
        if changed_field == "snapshot_revision":
            store.snapshot_revision += 1
        else:
            store.embedding_config_revision = "embedding-v2"

        retried = client.post(f"/memory/index/rebuild/{first['job_id']}/retry").json()["job"]
        _wait_for_job(client, retried["job_id"], "completed")

    assert retried["index_generation"] != first["index_generation"]
    assert retried["cursor_key"] is None
    assert retried["processed_count"] == 0
    assert store.received[1]["cursor_key"] is None
    assert store.received[1]["processed_count"] == 0
