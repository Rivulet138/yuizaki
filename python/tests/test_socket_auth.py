from modules.system.backend_api_auth import (
    backend_api_auth_required,
    verify_backend_api_authorization,
)
from socket_server import _socket_auth_allowed


def test_socket_auth_rejects_unknown_client_without_backend_token():
    assert _socket_auth_allowed(None, "") is False


def test_socket_auth_allows_loopback_without_token():
    assert _socket_auth_allowed(None, "", {"REMOTE_ADDR": "127.0.0.1"}) is True
    assert _socket_auth_allowed({}, "secret-token", {"asgi.scope": {"client": ("::1", 58421)}}) is True
    assert _socket_auth_allowed({}, "", {"REMOTE_ADDR": "192.168.1.20"}) is False


def test_socket_auth_accepts_backend_token_from_remote_auth_payload():
    remote = {"REMOTE_ADDR": "192.168.1.20"}
    assert _socket_auth_allowed({"token": "secret-token"}, "secret-token") is True
    assert _socket_auth_allowed({"authorization": "Bearer secret-token"}, "secret-token", remote) is True
    assert _socket_auth_allowed({"token": "wrong-token"}, "secret-token", remote) is False


def test_http_auth_skips_loopback_and_keeps_remote_token_boundary():
    assert backend_api_auth_required(
        "/api/settings", client_host="127.0.0.1"
    ) is False
    assert backend_api_auth_required(
        "/api/settings", client_host="192.168.1.20"
    ) is True
    assert verify_backend_api_authorization(
        None, "secret-token", client_host="::1"
    ) == (True, "")
    assert verify_backend_api_authorization(
        None, "secret-token", client_host="192.168.1.20"
    ) == (False, "Missing backend API token")
    assert verify_backend_api_authorization(
        "Bearer secret-token", "secret-token", client_host="192.168.1.20"
    ) == (True, "")


def test_external_connector_webhooks_use_provider_auth_only_on_exact_post_paths():
    for connector_id in ("telegram", "discord", "qq", "wechat"):
        path = f"/api/system/connectors/{connector_id}/webhook"
        assert backend_api_auth_required(path, "POST", client_host="203.0.113.10") is False
        assert backend_api_auth_required(path, "GET", client_host="203.0.113.10") is True
        assert backend_api_auth_required(f"{path}/extra", "POST", client_host="203.0.113.10") is True
        assert backend_api_auth_required(
            f"/api/system/connectors/{connector_id}/config", "GET", client_host="203.0.113.10"
        ) is True
