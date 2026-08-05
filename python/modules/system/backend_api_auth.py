from __future__ import annotations

import os
import secrets
from ipaddress import ip_address


PUBLIC_PREFIXES = ("/audio", "/socket.io", "/docs", "/redoc", "/openapi.json")
PROTECTED_PREFIXES = ("/api", "/memory", "/v1", "/vision", "/svc", "/system")
LOCAL_DEV_AUTH_BYPASS_ENV = "YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV"


def _env_flag_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


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


def unauthenticated_local_dev_allowed(client_host: str | None = None) -> bool:
    return _env_flag_enabled(os.getenv(LOCAL_DEV_AUTH_BYPASS_ENV)) and is_loopback_client(client_host)


def backend_api_auth_required(
    path: str,
    token: str,
    method: str = "GET",
    *,
    client_host: str | None = None,
) -> bool:
    if method.upper() == "OPTIONS":
        return False
    if path in {"/health", "/api/ping"}:
        return False
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in PUBLIC_PREFIXES):
        return False
    protected = any(path == prefix or path.startswith(f"{prefix}/") for prefix in PROTECTED_PREFIXES)
    if not protected:
        return False
    if not token and unauthenticated_local_dev_allowed(client_host):
        return False
    return True


def verify_backend_api_authorization(
    authorization: str | None,
    token: str,
    backend_token_header: str | None = None,
    *,
    client_host: str | None = None,
) -> tuple[bool, str]:
    if not token:
        if unauthenticated_local_dev_allowed(client_host):
            return True, ""
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
