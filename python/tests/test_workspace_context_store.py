from __future__ import annotations

import json

import pytest

from modules.system.workspace_context_store import (
    WorkspaceContextStore,
    MAX_CONTEXT_BYTES,
)


def test_context_store_persists_and_copies_values(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    store = WorkspaceContextStore(path)
    context = {"roleCard": {"enabled": True, "name": "A"}}

    written = store.put("default", context)
    written["roleCard"]["name"] = "mutated outside"
    assert store.get("default") == {"roleCard": {"enabled": True, "name": "A"}}

    reloaded = WorkspaceContextStore(path)
    assert reloaded.get("default") == {"roleCard": {"enabled": True, "name": "A"}}

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["workspaces"]["default"]["roleCard"]["name"] == "A"


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


def test_context_store_recovers_from_corrupt_file(tmp_path) -> None:
    path = tmp_path / "workspace_contexts.json"
    path.write_text("{not-json", encoding="utf-8")

    store = WorkspaceContextStore(path)

    assert store.get("default") is None
    assert list(tmp_path.glob("workspace_contexts.json.corrupt-*"))
    store.put("default", {"theme": "dark"})
    assert store.get("default") == {"theme": "dark"}
