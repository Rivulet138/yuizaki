from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SettingValueResponse(BaseModel):
    key: str
    value: Any


class RuntimeReloadSection(BaseModel):
    state: Literal["pending", "applying", "applied", "failed", "unavailable"]
    target_revision: int
    applied_revision: int | None = None
    error: str | None = None


class RuntimeReloadStatusResponse(BaseModel):
    sections: dict[str, RuntimeReloadSection] = Field(default_factory=dict)


class RuntimeReloadRetryRequest(BaseModel):
    targets: dict[str, int] = Field(min_length=1)


class SettingsMutationResponse(BaseModel):
    status: str
    updated: int | None = None
    key: str | None = None
    value: Any | None = None
    runtime_applied: list[str] = Field(default_factory=list)
    runtime_changed: list[str] = Field(default_factory=list)
    runtime_reload: RuntimeReloadStatusResponse = Field(default_factory=RuntimeReloadStatusResponse)


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
