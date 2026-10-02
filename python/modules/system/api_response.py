from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse


def error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
    legacy_error: str | None = None,
    legacy_fields: Mapping[str, Any] | None = None,
    legacy_detail: Any = None,
) -> JSONResponse:
    """Build a canonical envelope while exposing explicit migration fields."""
    payload: dict[str, Any] = {
        # ``error`` remains for older clients; ``code`` is the canonical field.
        "error": legacy_error or code,
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if details is not None:
        payload["details"] = details
    if request_id:
        payload["request_id"] = request_id
    if legacy_fields:
        payload.update(dict(legacy_fields))
    if legacy_detail is not None:
        payload["detail"] = legacy_detail
    return JSONResponse(payload, status_code=status_code, headers=headers)
