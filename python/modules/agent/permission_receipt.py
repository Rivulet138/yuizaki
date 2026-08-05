from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4


PERMISSION_RECEIPT_SCHEMA_VERSION = "yuizaki.permission-receipt.v1"
_REDACTED = "[REDACTED]"
_SECRET_KEY_PARTS = (
    "api_key", "apikey", "auth", "authorization", "cookie", "credential", "passphrase",
    "password", "private_key", "secret", "token",
)
_BEARER_PATTERN = re.compile(r"(?i)^\s*bearer\s+\S+")
_BASIC_AUTH_PATTERN = re.compile(r"(?i)^\s*basic\s+[A-Za-z0-9+/=_-]+\s*$")
_JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_PEM_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_API_KEY_PATTERN = re.compile(
    r"(?i)^(?:sk|pk|rk|ghp|github_pat|xox[baprs]|AIza)[-_A-Za-z0-9]{12,}$"
)
_URL_SECRET_KEYS = {"access_token", "api_key", "apikey", "auth", "authorization", "key", "password", "secret", "token"}

PermissionDecision = Literal["required", "allowed", "denied"]


def _is_secret_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _sanitize_url(value: str) -> tuple[str, bool]:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value, False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return value, False
    changed = parsed.username is not None or parsed.password is not None
    hostname = parsed.hostname or ""
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    try:
        port = parsed.port
    except ValueError:
        return value, False
    if port is not None:
        host = f"{host}:{port}"
    def sanitize_pairs(raw: str) -> tuple[str, bool]:
        pairs: list[tuple[str, str]] = []
        pairs_changed = False
        for key, item in parse_qsl(raw, keep_blank_values=True):
            if _is_secret_key(key) or key.lower() in _URL_SECRET_KEYS or _looks_secret(item):
                pairs.append((key, _REDACTED))
                pairs_changed = True
            else:
                pairs.append((key, item))
        return urlencode(pairs), pairs_changed

    query, query_changed = sanitize_pairs(parsed.query)
    changed = changed or query_changed
    fragment = parsed.fragment
    if "=" in fragment:
        fragment, fragment_changed = sanitize_pairs(fragment)
        changed = changed or fragment_changed
    return urlunsplit((parsed.scheme, host, parsed.path, query, fragment)), changed


def _looks_secret(value: str) -> bool:
    stripped = value.strip()
    return bool(
        _BEARER_PATTERN.match(stripped)
        or _BASIC_AUTH_PATTERN.match(stripped)
        or _JWT_PATTERN.fullmatch(stripped)
        or _API_KEY_PATTERN.fullmatch(stripped)
        or _PEM_PRIVATE_KEY_PATTERN.search(stripped)
        or (
            len(stripped) >= 32
            and re.fullmatch(r"[A-Za-z0-9_-]+", stripped) is not None
            and any(char.isalpha() for char in stripped)
            and any(char.isdigit() for char in stripped)
        )
    )


def redact_permission_parameters(parameters: Any) -> tuple[Any, list[str]]:
    """Return a JSON-safe recursively redacted copy and its redacted paths."""

    redacted_paths: list[str] = []

    def visit(value: Any, path: str, *, secret: bool = False) -> Any:
        if secret:
            redacted_paths.append(path)
            return _REDACTED
        if isinstance(value, dict):
            header_name = value.get("name")
            structured_secret_header = (
                isinstance(header_name, str)
                and _is_secret_key(header_name)
                and "value" in value
            )
            return {
                str(key): visit(
                    item,
                    f"{path}.{key}",
                    secret=_is_secret_key(key) or (structured_secret_header and str(key).lower() == "value"),
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [visit(item, f"{path}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, str):
            sanitized_url, url_changed = _sanitize_url(value)
            if url_changed:
                redacted_paths.append(path)
                return sanitized_url
            if _looks_secret(value):
                redacted_paths.append(path)
                return _REDACTED
        return value

    return visit(parameters, "$"), redacted_paths


@dataclass(frozen=True)
class PermissionReceipt:
    agent_request_id: str
    permission_request_id: str
    capability_call_id: str
    decision: PermissionDecision
    reason_code: str
    retryable: bool
    permission_scope: str
    capability_id: str
    capability_type: str
    capability_kind: str
    risk_level: str
    parameters: Any
    redacted_paths: list[str]
    decided_at: str | None = None
    schema_version: str = PERMISSION_RECEIPT_SCHEMA_VERSION


def build_permission_receipt(
    *,
    agent_request_id: str,
    decision: PermissionDecision,
    reason_code: str,
    retryable: bool,
    permission_scope: str,
    capability_id: str,
    capability_type: str,
    capability_kind: str,
    risk_level: str,
    parameters: Any,
    permission_request_id: str | None = None,
    capability_call_id: str | None = None,
    decided_at: str | None = None,
) -> PermissionReceipt:
    safe_parameters, redacted_paths = redact_permission_parameters(parameters)
    call_id = capability_call_id or f"call_{uuid4().hex[:12]}"
    return PermissionReceipt(
        agent_request_id=agent_request_id,
        permission_request_id=permission_request_id or f"perm_{uuid4().hex[:12]}",
        capability_call_id=call_id,
        decision=decision,
        reason_code=reason_code,
        retryable=retryable,
        permission_scope=permission_scope,
        capability_id=capability_id,
        capability_type=capability_type,
        capability_kind=capability_kind,
        risk_level=risk_level,
        parameters=safe_parameters,
        redacted_paths=redacted_paths,
        decided_at=decided_at,
    )


def serialize_permission_receipt(receipt: PermissionReceipt | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    data = asdict(receipt)
    safe_parameters, discovered_paths = redact_permission_parameters(receipt.parameters)
    data["parameters"] = safe_parameters
    data["redacted_paths"] = list(dict.fromkeys([*receipt.redacted_paths, *discovered_paths]))
    return data


def serialize_permission_payload(value: Any) -> Any:
    """Serialize receipts anywhere in a response payload without rebuilding their schema."""

    if isinstance(value, PermissionReceipt):
        return serialize_permission_receipt(value)
    if isinstance(value, dict):
        return {str(key): serialize_permission_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_permission_payload(item) for item in value]
    return value
