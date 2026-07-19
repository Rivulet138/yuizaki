from __future__ import annotations

import secrets

from fastapi import HTTPException

from .api_response import error_response


def require_bearer_token(
    authorization: str | None,
    expected_token: str,
):
    token = (expected_token or "").strip()
    if not token:
        return None

    bearer = (authorization or "").strip()
    if not bearer.startswith("Bearer "):
        return error_response(
            code="unauthorized",
            message="Missing Bearer token",
            status_code=401,
        )

    provided = bearer[7:].strip()
    if not secrets.compare_digest(provided, token):
        return error_response(
            code="unauthorized",
            message="Invalid admin token",
            status_code=401,
        )

    return None


def ensure_safe_relative_json_path(filepath: str, *, field_name: str = "filepath") -> str:
    value = (filepath or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if value.startswith("/") or value.startswith("\\") or ":" in value:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a relative path")
    normalized = value.replace("\\", "/")
    parts = [segment for segment in normalized.split("/") if segment not in {"", "."}]
    if not parts or any(segment == ".." for segment in parts):
        raise HTTPException(status_code=400, detail=f"{field_name} must stay within the managed transfer directory")
    if not normalized.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail=f"{field_name} must end with .json")
    return "/".join(parts)
