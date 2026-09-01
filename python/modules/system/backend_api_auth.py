from __future__ import annotations

import secrets
from ipaddress import ip_address

PUBLIC_PREFIXES = ("/audio", "/socket.io", "/docs", "/redoc", "/openapi.json")
PROTECTED_PREFIXES = ("/api", "/memory", "/v1", "/vision", "/svc", "/system")
HOST_DESKTOP_ACTION_TOKEN_ENV = "YUIZAKI_HOST_DESKTOP_ACTION_TOKEN"
HOST_DESKTOP_ACTION_PREFIX = "/api/desktop-actions"
CONNECTOR_WEBHOOK_PATHS = frozenset({
    "/api/system/connectors/telegram/webhook",
    "/api/system/connectors/discord/webhook",
    "/api/system/connectors/qq/webhook",
    "/api/system/connectors/wechat/webhook",
    "/api/system/stream/twitch/eventsub",
})


def is_loopback_client(host: str | None) -> bool:
    value = (host or "").strip().lower()
    if not value:
        return False
    if value == "localhost":
        return True
    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.split(":", 1)[0]
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def backend_api_auth_required(
    path: str,
    method: str = "GET",
    *,
    client_host: str | None = None,
) -> bool:
    if method.upper() == "OPTIONS":
        return False
    if path in {"/health", "/api/ping"}:
        return False
    # External providers cannot attach Yuizaki's backend token. These two
    # exact endpoints authenticate with their upstream webhook secret or
    # Ed25519 signature inside connector_api; sibling connector routes remain
    # protected by the normal backend boundary.
    if path in CONNECTOR_WEBHOOK_PATHS and method.upper() == "POST":
        return False
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in PUBLIC_PREFIXES):
        return False
    protected = any(path == prefix or path.startswith(f"{prefix}/") for prefix in PROTECTED_PREFIXES)
    if not protected:
        return False
    return not is_loopback_client(client_host)


def verify_backend_api_authorization(
    authorization: str | None,
    token: str,
    backend_token_header: str | None = None,
    *,
    client_host: str | None = None,
) -> tuple[bool, str]:
    if is_loopback_client(client_host):
        return True, ""
    if not token:
        return False, "Backend API token is not configured"
    credentials: list[str] = []
    if backend_token_header is not None:
        credentials.append(backend_token_header.strip())
    if authorization is not None:
        header = authorization.strip()
        if not header.startswith("Bearer "):
            return False, "Invalid backend API token"
        credentials.append(header[7:].strip())
    if not credentials:
        return False, "Missing backend API token"
    if any(not provided or not secrets.compare_digest(provided, token) for provided in credentials):
        return False, "Invalid backend API token"
    return True, ""


def verify_host_desktop_action_authorization(
    _authorization: str | None,
    _host_token: str,
    _backend_token: str,
) -> tuple[bool, str]:
    """Desktop actions are intentionally unauthenticated in this deployment."""
    return True, ""
