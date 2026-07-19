from modules.system.backend_api_auth import backend_api_auth_required, verify_backend_api_authorization


def test_ping_is_public_when_backend_token_is_enabled():
    assert backend_api_auth_required("/api/ping", "secret-token") is False


def test_options_preflight_is_public_when_backend_token_is_enabled():
    assert backend_api_auth_required("/api/settings", "secret-token", "OPTIONS") is False


def test_protected_api_routes_still_require_backend_token():
    assert backend_api_auth_required("/api/settings", "secret-token") is True


def test_protected_api_routes_fail_closed_when_backend_token_is_missing(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert backend_api_auth_required("/api/settings", "") is True
    assert verify_backend_api_authorization(None, "") == (False, "Backend API token is not configured")


def test_missing_backend_token_rejects_loopback_without_explicit_override(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert backend_api_auth_required("/api/settings", "", client_host="127.0.0.1") is True
    assert backend_api_auth_required("/api/settings", "", client_host="localhost") is True
    assert verify_backend_api_authorization(None, "", client_host="::1") == (
        False,
        "Backend API token is not configured",
    )


def test_missing_backend_token_still_rejects_non_loopback_clients(monkeypatch):
    monkeypatch.delenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", raising=False)

    assert backend_api_auth_required("/api/settings", "", client_host="192.168.1.20") is True
    assert verify_backend_api_authorization(None, "", client_host="192.168.1.20") == (
        False,
        "Backend API token is not configured",
    )


def test_explicit_local_dev_override_disables_backend_api_auth(monkeypatch):
    monkeypatch.setenv("YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV", "true")

    assert backend_api_auth_required("/api/settings", "", client_host="127.0.0.1") is False
    assert verify_backend_api_authorization(None, "", client_host="::1") == (True, "")
    assert backend_api_auth_required("/api/settings", "", client_host="192.168.1.20") is True
