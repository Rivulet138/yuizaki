import pytest
from types import SimpleNamespace

from socket_server import ChatPersistenceError, DesktopPetSocketServer


def _server(*, allow_legacy: bool) -> DesktopPetSocketServer:
    server = DesktopPetSocketServer.__new__(DesktopPetSocketServer)
    server.turn_service = None
    server.agent_pipeline = object()
    server._allow_legacy_turn_pipeline = allow_legacy
    return server


def test_semantic_socket_execution_fails_closed_without_turn_service() -> None:
    server = _server(allow_legacy=False)

    with pytest.raises(RuntimeError, match="TurnService is required"):
        server._semantic_turn_service()


def test_legacy_socket_execution_requires_explicit_compatibility_flag() -> None:
    server = _server(allow_legacy=True)

    assert server._semantic_turn_service() is None


def test_legacy_chat_persistence_fails_closed_without_repository() -> None:
    server = _server(allow_legacy=True)
    server.runtime_context = SimpleNamespace(db_repo=None)

    with pytest.raises(ChatPersistenceError, match="repository is unavailable"):
        server._persist_chat_exchange(
            session_id="session-1",
            workspace_id="workspace-1",
            messages=[{"role": "user", "content": "hello"}],
            assistant_text="hi",
        )
