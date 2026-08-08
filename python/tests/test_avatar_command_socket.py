from socket_server import DesktopPetSocketServer


def test_avatar_command_sequences_are_monotonic_across_sessions() -> None:
    server = DesktopPetSocketServer.__new__(DesktopPetSocketServer)
    server._avatar_command_sequence = 0
    server._avatar_command_stream_id = "python:test"

    first = server._build_avatar_command(
        {"emotion_id": "happy"},
        session_id="chat-session",
        request_id="request-a",
    )
    second = server._build_avatar_command(
        {"emotion_id": "calm"},
        session_id="voice-session",
        request_id="request-b",
    )

    assert first is not None
    assert second is not None
    assert first["sequence"] == 0
    assert second["sequence"] == 1
    assert first["streamId"] == "python:test"
    assert second["streamId"] == "python:test"
    assert first["id"] == "request-a-avatar-0"
    assert second["id"] == "request-b-avatar-1"
