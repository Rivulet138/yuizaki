from __future__ import annotations

from fastapi import HTTPException


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
