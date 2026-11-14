"""Exercise app lifecycle hooks without importing app or opening user data."""
from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from modules.system.dynamic_config import DynamicConfigManager
from modules.system.settings_api import SettingsAPI
from modules.system.settings_history_store import SettingsHistoryStore
from modules.system.settings_schema import PersistedSettingsSchema
from modules.system.settings_store import SettingsStore


def app_hooks(**bindings):
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names = {"_reload_memory_runtime", "_init_llm", "_init_llm_for_settings"}
    definitions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    namespace = {"asyncio": asyncio, "logger": logging.getLogger(__name__), **bindings}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102 - execute only selected trusted local hook definitions, never app startup
    return namespace


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["add", "list"])
async def test_memory_reload_failure_reaches_settings_status_and_keeps_authority(tmp_path: Path, failure_stage: str) -> None:
    class PreviousStore:
        def list_documents(self):
            return [SimpleNamespace(id="synthetic")]

    class BrokenStore:
        def add_document(self, _document):
            if failure_stage == "add":
                raise RuntimeError("synthetic migration failure")

        def list_documents(self):
            raise RuntimeError("synthetic hydration failure")

    previous = PreviousStore()
    state = SimpleNamespace(store=previous, pipeline="previous-pipeline")
    defaults = PersistedSettingsSchema().model_dump()
    store = SettingsStore(tmp_path / "settings.json")
    store.replace(defaults)
    config = SimpleNamespace(**{key: SimpleNamespace(**value) for key, value in defaults.items() if isinstance(value, dict)})
    hooks = app_hooks(
        _memory_reload_lock=asyncio.Lock(), _memory_state=state,
        config=config, create_memory_backend=lambda _config: BrokenStore(), _retrieval_pipeline="previous-pipeline",
    )

    async def reload(_changed):
        await hooks["_reload_memory_runtime"]()

    api = SettingsAPI(store, DynamicConfigManager(), config=config, reload_runtime_services=reload,
                      settings_history_store=SettingsHistoryStore(tmp_path / "history.json"))
    await api.update_settings({"memory": {"sqlite_path": str(tmp_path / "new-authority.sqlite")}})
    await api.wait_for_runtime_reload_idle()
    status = await api.get_runtime_reload_status()
    assert status.sections["memory"].state == "failed"
    assert status.sections["memory"].applied_revision is None
    assert state.store is previous
    assert state.pipeline == "previous-pipeline"
    assert hooks["_retrieval_pipeline"] == "previous-pipeline"


@pytest.mark.asyncio
async def test_missing_memory_authority_does_not_report_success() -> None:
    hooks = app_hooks(_memory_reload_lock=asyncio.Lock(), _memory_state=None)
    with pytest.raises(RuntimeError, match="memory_store_not_initialized"):
        await hooks["_reload_memory_runtime"]()


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_vision_failure_propagates_for_settings_but_preserves_optional_startup(strict: bool) -> None:
    container = {}
    client = object()

    async def initialize_llm(_config, _logger):
        return client

    async def initialize_vision(_config, _logger):
        raise RuntimeError("synthetic vision init failure")

    hooks = app_hooks(
        _llm_client=None, _vision_llm_client="old-vision", config=object(),
        runtime_container=SimpleNamespace(set=container.__setitem__, remove=lambda key: container.pop(key, None)),
        _runtime_services=lambda: SimpleNamespace(initialize_llm=initialize_llm, initialize_vision_llm=initialize_vision),
    )
    if strict:
        with pytest.raises(RuntimeError, match="vision init failure"):
            await hooks["_init_llm_for_settings"]()
    else:
        await hooks["_init_llm"]()
    assert hooks["_vision_llm_client"] is None
    assert container.get("llm") is client
    assert "vision_llm" not in container
