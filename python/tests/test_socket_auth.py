from socket_server import _socket_auth_allowed


def test_socket_auth_fails_closed_without_backend_token(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert _socket_auth_allowed(None, "") is False


def test_socket_auth_rejects_loopback_without_explicit_override(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert _socket_auth_allowed(None, "", {"REMOTE_ADDR": "127.0.0.1"}) is False
    assert _socket_auth_allowed({}, "", {"asgi.scope": {"client": ("::1", 58421)}}) is False
    assert _socket_auth_allowed({}, "", {"REMOTE_ADDR": "192.168.1.20"}) is False


def test_socket_auth_can_be_explicitly_disabled_for_local_dev(monkeypatch):
    monkeypatch.setenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "1")

    assert _socket_auth_allowed(None, "", {"REMOTE_ADDR": "127.0.0.1"}) is True
    assert _socket_auth_allowed(None, "") is False


def test_socket_auth_accepts_backend_token_from_auth_payload(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert _socket_auth_allowed({"token": "secret-token"}, "secret-token") is True
    assert _socket_auth_allowed({"authorization": "Bearer secret-token"}, "secret-token") is True
    assert _socket_auth_allowed({"token": "wrong-token"}, "secret-token") is False
