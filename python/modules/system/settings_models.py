from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

class SettingValueResponse(BaseModel):
    key: str
    value: Any


class SettingsMutationResponse(BaseModel):
    status: str
    updated: int | None = None
    key: str | None = None
    value: Any | None = None
    runtime_applied: list[str] = Field(default_factory=list)
    runtime_changed: list[str] = Field(default_factory=list)


class SettingsExportResponse(BaseModel):
    filepath: str
    status: str


class SettingsImportResponse(BaseModel):
    filepath: str
    status: str
    runtime_applied: list[str] = Field(default_factory=list)
    runtime_changed: list[str] = Field(default_factory=list)


class SettingsHistoryEntry(BaseModel):
    key: str
    old_value: Any
    new_value: Any
    timestamp: str


class SettingsHistoryResponse(BaseModel):
    history: list[SettingsHistoryEntry]
    count: int


class SettingsMetadataResponse(BaseModel):
    path: str
    size_bytes: int | None = None
    last_modified: str | None = None
    settings_count: int | None = None
    exists: bool | None = None


class SettingsRollbackResponse(BaseModel):
    steps: int
    status: str
