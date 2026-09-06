import pytest

from socket_server import DesktopPetSocketServer


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
