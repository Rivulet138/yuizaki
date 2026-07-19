from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "error": code,
        "message": message,
    }
    if details:
        payload["details"] = details
    return JSONResponse(payload, status_code=status_code, headers=headers)
