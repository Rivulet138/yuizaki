from __future__ import annotations

import json

import pytest

from modules.system.workspace_context_store import (
    MAX_CONTEXT_BYTES,
    WorkspaceContextConflict,
    WorkspaceContextStore,
)


def test_context_store_persists_and_copies_values(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    store = WorkspaceContextStore(path)
    context = {"roleCard": {"enabled": True, "name": "A"}}

    written = store.put("default", context)
    written["context"]["roleCard"]["name"] = "mutated outside"
    assert store.get("default") == {"roleCard": {"enabled": True, "name": "A"}}

    reloaded = WorkspaceContextStore(path)
    assert reloaded.get("default") == {"roleCard": {"enabled": True, "name": "A"}}

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["workspaces"]["default"]["context"]["roleCard"]["name"] == "A"
    assert payload["workspaces"]["default"]["revision"] == 1


def test_context_store_bumps_revision_and_rejects_stale_writes(tmp_path) -> None:
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    first = store.put("default", {"theme": "dark"})
    assert first["revision"] == 1

    second = store.put("default", {"theme": "light"}, expected_revision=1)
    assert second["revision"] == 2

    with pytest.raises(WorkspaceContextConflict):
        store.put("default", {"theme": "stale"}, expected_revision=1)
    assert store.get("default") == {"theme": "light"}


def test_context_store_reads_v1_files(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    path.write_text(
        json.dumps({"version": 1, "workspaces": {"default": {"roleCard": {"enabled": True}}}}),
        encoding="utf-8",
    )

    store = WorkspaceContextStore(path)

    assert store.get("default") == {"roleCard": {"enabled": True}}
    entry = store.get_entry("default")
    assert entry is not None and entry["revision"] == 0


def test_second_process_write_keeps_the_first_entry(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    first = WorkspaceContextStore(path)
    second = WorkspaceContextStore(path)

    first.put("scene-a", {"roleCard": {"name": "A"}})
    second.put("scene-b", {"roleCard": {"name": "B"}})

    reloaded = WorkspaceContextStore(path)
    assert reloaded.get("scene-a") == {"roleCard": {"name": "A"}}
    assert reloaded.get("scene-b") == {"roleCard": {"name": "B"}}


def test_concurrent_store_instances_do_not_lose_entries(tmp_path) -> None:
    import threading

    path = tmp_path / "workspace_contexts.json"
    errors: list[BaseException] = []

    def worker(name: str, count: int) -> None:
        try:
            store = WorkspaceContextStore(path)
            for index in range(count):
                store.put(f"{name}-{index}", {"roleCard": {"name": f"{name}{index}"}})
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"t{index}", 8)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    reloaded = WorkspaceContextStore(path)
    assert len(reloaded._entries) == 32


def test_context_store_deletes_workspace(tmp_path) -> None:
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    store.put("default", {"worldBook": {"enabled": True}})
    store.delete("default")

    assert store.get("default") is None
    assert WorkspaceContextStore(tmp_path / "workspace_contexts.json").get("default") is None


def test_context_store_rejects_non_object_and_oversized_values(tmp_path) -> None:
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")

    with pytest.raises(ValueError, match="JSON object"):
        store.put("default", ["not", "an", "object"])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="too large"):
        store.put("default", {"value": "x" * (MAX_CONTEXT_BYTES + 1)})


def test_corrupt_file_is_quarantined_before_a_write_replaces_it(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    path.write_text("{not-json", encoding="utf-8")
    store = WorkspaceContextStore(path)
    assert list(tmp_path.glob("workspace_contexts.json.corrupt-*"))

    store.put("default", {"theme": "dark"})

    backups = list(tmp_path.glob("workspace_contexts.json.corrupt-*"))
    assert backups, "the damaged file must be preserved"
    assert backups[0].read_text(encoding="utf-8") == "{not-json"


def test_context_store_recovers_from_corrupt_file(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    path.write_text("{not-json", encoding="utf-8")

    store = WorkspaceContextStore(path)

    assert store.get("default") is None
    assert list(tmp_path.glob("workspace_contexts.json.corrupt-*"))
    store.put("default", {"theme": "dark"})
    assert store.get("default") == {"theme": "dark"}
