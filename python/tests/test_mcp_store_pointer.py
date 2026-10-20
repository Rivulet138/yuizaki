from __future__ import annotations

import json
import threading

import pytest

from modules.agent.mcp_manager import MCPManager
from modules.tools.mcp_bridge import MCPToolError


def _pointer(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manager(path) -> MCPManager:
    return MCPManager(path)


def test_pointer_generation_advances_on_each_save(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    manager = _manager(store)

    manager.add_server("first", "http://127.0.0.1:1111/mcp")
    first = _pointer(store)["generation"]
    manager.add_server("second", "http://127.0.0.1:2222/mcp")

    assert first >= 1
    assert _pointer(store)["generation"] == first + 1


def test_legacy_pointer_without_generation_is_readable(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    store.write_text(json.dumps({
        "servers": {
            "legacy": {"base_url": "http://127.0.0.1:3333/mcp", "transport": "http", "enabled": True}
        }
    }), encoding="utf-8")

    manager = _manager(store)

    assert "legacy" in manager.servers
    manager.add_server("added", "http://127.0.0.1:4444/mcp")
    # A legacy file is upgraded (builtin presets merge) on load, so the
    # generation is whatever that upgrade produced plus this write.
    assert _pointer(store)["generation"] >= 1
    assert "added" in _pointer(store)["servers"]


def test_stale_writer_conflicts_instead_of_clobbering(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    winner = _manager(store)
    stale = _manager(store)
    winner.add_server("winner", "http://127.0.0.1:5555/mcp")

    with pytest.raises(MCPToolError, match="vault_pointer_conflict"):
        stale.add_server("stale", "http://127.0.0.1:6666/mcp")

    names = set(_pointer(store)["servers"])
    assert "winner" in names
    assert "stale" not in names


def test_stale_writer_recovers_after_reload(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    winner = _manager(store)
    stale = _manager(store)
    winner.add_server("winner", "http://127.0.0.1:5555/mcp")

    stale._load_store()
    stale.add_server("stale", "http://127.0.0.1:6666/mcp")

    names = set(_pointer(store)["servers"])
    assert {"winner", "stale"} <= names


def test_unreadable_pointer_fails_closed(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    manager = _manager(store)
    store.write_text("{broken", encoding="utf-8")

    with pytest.raises(MCPToolError, match="vault_pointer_conflict"):
        manager.add_server("blocked", "http://127.0.0.1:7777/mcp")

    assert store.read_text(encoding="utf-8") == "{broken"


def test_lock_file_lives_next_to_the_pointer(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    manager = _manager(store)

    manager.add_server("first", "http://127.0.0.1:1111/mcp")

    assert (tmp_path / "mcp.json.lock").exists()


def test_concurrent_writers_keep_every_server(tmp_path) -> None:
    store = tmp_path / "mcp.json"
    manager = _manager(store)
    names = [f"server-{index}" for index in range(8)]
    errors: list[BaseException] = []

    def add(name: str) -> None:
        try:
            manager.add_server(name, f"http://127.0.0.1:{8000 + int(name.split('-')[1])}/mcp")
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    stored = _pointer(store)
    # Builtin presets are merged in on load; every concurrent write must
    # still be present.
    assert set(names) <= set(stored["servers"])
    assert isinstance(stored["generation"], int) and stored["generation"] >= len(names)
