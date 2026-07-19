"""Settings API endpoints - REST API for configuration management."""

from __future__ import annotations

import asyncio
import logging
import json
from copy import deepcopy
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Protocol, TypeGuard, cast

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..llm.client import fetch_available_models
from ..llm.providers import normalize_llm_base_url, normalize_llm_provider
from ..tts.capabilities import resolve_tts_provider_capabilities
from .api_security import ensure_safe_relative_json_path, require_bearer_token
from .dynamic_config import redact_sensitive_config_value
from .runtime_config import RuntimeConfig
from .service_discovery import discover_local_runtime_candidates
from .settings_models import SettingValueResponse, SettingsExportResponse, SettingsHistoryResponse, SettingsImportResponse, SettingsMetadataResponse, SettingsMutationResponse, SettingsRollbackResponse
from .settings_store import SETTINGS_SECRET_MASK
from .settings_schema import (
    PersistedSettingsSchema,
    merge_settings,
    validate_persisted_settings,
    validate_runtime_patch,
    validation_errors_to_detail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])
_settings_api: SettingsAPI | None = None
_RUNTIME_SETTING_SECTIONS = {"llm", "tts", "asr", "svc", "summary", "memory"}
_RUNTIME_RELOAD_FIELDS: dict[str, set[str]] = {
    "llm": {
        "provider", "base_url", "api_key", "model", "timeout",
        "vision_enabled", "vision_provider", "vision_base_url", "vision_api_key", "vision_model", "vision_timeout",
    },
    "tts": {"genie_character", "genie_model_dir", "lang", "ref_audio", "ref_text", "device", "quality", "split", "mode", "save_mode"},
    "asr": {
        "provider",
        "base_url",
        "api_key",
        "timeout",
        "sensevoice_model",
        "sensevoice_device",
        "sherpa_model_path",
        "sherpa_tokens_path",
        "sherpa_num_threads",
        "sherpa_provider",
        "language",
        "vad_threshold",
        "vad_min_silence_ms",
        "asr_partial_every",
    },
    "svc": {"provider", "base_url", "speaker_id", "pitch", "timeout"},
    "memory": {
        "backend",
        "sqlite_path",
        "qdrant_url",
        "qdrant_api_key",
        "qdrant_collection",
        "qdrant_timeout",
        "qdrant_auto_start",
        "qdrant_docker_image",
        "qdrant_docker_container",
        "qdrant_docker_volume",
        "embedding_model",
    },
    "summary": {
        "trigger_messages",
        "keep_recent_messages",
        "item_max_chars",
        "rewrite_interval_messages",
        "quality_scorer_mode",
        "quality_score_cooldown_seconds",
        "quality_score_budget_per_hour",
    },
}

_SECRET_FIELD_NAMES = {"api_key", "vision_api_key", "qdrant_api_key"}


def _mask_sensitive_settings(value: object) -> object:
    if isinstance(value, list):
        return [_mask_sensitive_settings(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    return {
        key: SETTINGS_SECRET_MASK if key in _SECRET_FIELD_NAMES and bool(child) else _mask_sensitive_settings(child)
        for key, child in value.items()
    }


def _drop_secret_placeholders(value: object) -> object:
    if isinstance(value, list):
        return [_drop_secret_placeholders(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    result: dict[str, object] = {}
    for key, child in value.items():
        if key in _SECRET_FIELD_NAMES and child == SETTINGS_SECRET_MASK:
            continue
        cleaned = _drop_secret_placeholders(child)
        if isinstance(child, dict) and isinstance(cleaned, dict) and not cleaned:
            continue
        result[key] = cleaned
    return result


def _preserve_current_secrets(target: object, current: object) -> object:
    if not isinstance(target, dict) or not isinstance(current, dict):
        return deepcopy(target)
    result = deepcopy(target)
    for key, current_child in current.items():
        if key in _SECRET_FIELD_NAMES:
            result[key] = deepcopy(current_child)
            continue
        target_child = result.get(key)
        if isinstance(target_child, dict) and isinstance(current_child, dict):
            result[key] = _preserve_current_secrets(target_child, current_child)
    return result


def _changed_runtime_updates(
    current_settings: dict[str, object],
    runtime_updates: dict[str, object],
) -> dict[str, object]:
    """Keep only runtime fields whose validated persisted value actually changed."""
    changed: dict[str, object] = {}
    missing = object()
    for section, section_updates in runtime_updates.items():
        current_section = current_settings.get(section)
        if not isinstance(section_updates, dict) or not isinstance(current_section, dict):
            if current_section != section_updates:
                changed[section] = deepcopy(section_updates)
            continue
        changed_fields = {
            key: deepcopy(value)
            for key, value in section_updates.items()
            if current_section.get(key, missing) != value
        }
        if changed_fields:
            changed[section] = changed_fields
    return changed


class SettingsStoreProtocol(Protocol):
    def get_all(self) -> dict[str, object]: ...
    def replace(self, settings: dict[str, object]) -> None: ...
    def save(self) -> None: ...
    def get(self, key: str) -> object | None: ...
    def export_managed(self, relative_path: str) -> Path: ...
    def import_managed(self, relative_path: str) -> Path: ...
    def get_metadata(self) -> dict[str, object]: ...


class DynamicConfigProtocol(Protocol):
    config: dict[str, object]

    async def update_batch(self, updates: dict[str, object]) -> bool: ...
    def get_all(self) -> dict[str, object]: ...
    def get_history(self, key: str | None, limit: int) -> list[dict[str, object]]: ...
    def rollback(self, steps: int) -> bool: ...
    def clear_history(self) -> None: ...


class TestableClientProtocol(Protocol):
    async def test_connection(self) -> dict[str, object]: ...


ReloadRuntimeServices = Callable[[set[str]], Awaitable[None]]
ClientProvider = Callable[[], TestableClientProtocol | None]
RuntimeApplyResult = dict[str, list[str]]


def _is_settings_map(value: object) -> TypeGuard[dict[str, object]]:
    if not isinstance(value, dict):
        return False
    value_map = cast(dict[object, object], value)
    return all(isinstance(key, str) for key in value_map)


def _first_string(source: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str):
            return value
    return None


def _first_number(source: dict[str, object], keys: tuple[str, ...]) -> float | int | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            clean_value = value.strip()
            if not clean_value:
                continue
            try:
                return float(clean_value)
            except ValueError:
                continue
    return None


def normalize_inline_llm_import_payload(payload: dict[str, object]) -> dict[str, object]:
    known_sections = set(PersistedSettingsSchema.model_fields)
    if any(isinstance(payload.get(key), dict) for key in known_sections):
        return payload

    nested_source: dict[str, object] | None = None
    for key in ("connectionProfile", "profile", "preset", "api", "connection"):
        value = payload.get(key)
        if isinstance(value, dict) and all(isinstance(item_key, str) for item_key in value):
            nested_source = cast(dict[str, object], value)
            break

    source = nested_source or payload
    llm: dict[str, object] = {}
    string_fields: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("provider", ("provider", "llmProvider", "providerPreset")),
        ("base_url", ("base_url", "baseUrl", "api_url", "apiUrl", "server_url", "serverUrl", "endpoint")),
        ("api_key", ("api_key", "apiKey", "key", "token", "secret")),
        ("model", ("model", "model_name", "modelName", "chat_model", "chatModel")),
    )
    for target, keys in string_fields:
        value = _first_string(source, keys)
        if value is not None:
            llm[target] = value

    number_fields: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("timeout", ("timeout", "request_timeout", "requestTimeout")),
        (
            "context_max_tokens",
            (
                "context_max_tokens",
                "contextMaxTokens",
                "context_size",
                "contextSize",
                "max_context",
                "maxContext",
                "openai_max_context",
                "openaiMaxContext",
            ),
        ),
        (
            "default_max_output_tokens",
            (
                "default_max_output_tokens",
                "max_output_tokens",
                "maxOutputTokens",
                "max_tokens",
                "maxTokens",
                "openai_max_tokens",
                "openaiMaxTokens",
            ),
        ),
        ("temperature", ("temperature", "temp")),
        ("top_p", ("top_p", "topP")),
        ("top_k", ("top_k", "topK")),
        ("min_p", ("min_p", "minP")),
        ("frequency_penalty", ("frequency_penalty", "frequencyPenalty")),
        ("presence_penalty", ("presence_penalty", "presencePenalty")),
        ("repetition_penalty", ("repetition_penalty", "repetitionPenalty", "repeat_penalty", "repeatPenalty", "rep_penalty", "repPenalty")),
    )
    for target, keys in number_fields:
        value = _first_number(source, keys)
        if value is not None:
            llm[target] = value

    return {"llm": llm} if llm else payload


def get_settings_api() -> "SettingsAPI":
    if _settings_api is None:
        raise HTTPException(status_code=503, detail="Settings API not initialized")
    return _settings_api


class SettingsAPI:
    """Settings API handler."""

    def __init__(
        self,
        settings_store: SettingsStoreProtocol,
        dynamic_config: DynamicConfigProtocol,
        config: object | None = None,
        reload_runtime_services: ReloadRuntimeServices | None = None,
        llm_client_provider: ClientProvider | None = None,
        tts_client_provider: ClientProvider | None = None,
    ):
        self.settings_store: SettingsStoreProtocol = settings_store
        self.dynamic_config: DynamicConfigProtocol = dynamic_config
        self.config: object | None = config
        self.reload_runtime_services: ReloadRuntimeServices | None = reload_runtime_services
        self.llm_client_provider: ClientProvider | None = llm_client_provider
        self.tts_client_provider: ClientProvider | None = tts_client_provider
        self._settings_snapshots: list[dict[str, object]] = []
        self._pending_runtime_reload: set[str] = set()
        self._runtime_reload_task: asyncio.Task[None] | None = None
        self._store_lock = asyncio.Lock()

    def _validated_settings_dump(self) -> dict[str, object]:
        return validate_persisted_settings(self.settings_store.get_all()).model_dump()

    async def _run_store_call(self, callback: Callable[[], object]) -> object:
        async with self._store_lock:
            return await asyncio.to_thread(callback)

    async def _validated_settings_dump_async(self) -> dict[str, object]:
        return cast(dict[str, object], await self._run_store_call(self._validated_settings_dump))

    def _replace_and_save_settings(self, settings: dict[str, object]) -> None:
        self.settings_store.replace(settings)
        self.settings_store.save()

    def _normalize_set_payload(self, key: str, value: object) -> dict[str, object]:
        keys = key.split(".")
        payload: dict[str, object] = {}
        current = payload
        for part in keys[:-1]:
            next_level: dict[str, object] = {}
            current[part] = next_level
            current = next_level
        current[keys[-1]] = value
        return payload

    def _value_for_key(self, settings: dict[str, object], key: str) -> object:
        current: object = settings
        for part in key.split("."):
            if not _is_settings_map(current):
                raise KeyError(key)
            if part not in current:
                raise KeyError(key)
            current = current[part]
        return current

    def _runtime_payload(self, payload: dict[str, object]) -> dict[str, object]:
        return {key: value for key, value in payload.items() if key in _RUNTIME_SETTING_SECTIONS}

    def _validated_runtime_updates(self, payload: dict[str, object]) -> dict[str, object]:
        runtime_payload = self._runtime_payload(payload)
        if not runtime_payload:
            return {}
        return validate_runtime_patch(runtime_payload).model_dump(exclude_none=True, exclude_unset=True)

    def _runtime_reload_sections(self, runtime_updates: dict[str, object], changed: set[str]) -> set[str]:
        sections: set[str] = set()
        for section in changed:
            section_updates = runtime_updates.get(section)
            reload_fields = _RUNTIME_RELOAD_FIELDS.get(section)
            if reload_fields is None:
                sections.add(section)
                continue
            if isinstance(section_updates, dict):
                if reload_fields.intersection(section_updates):
                    sections.add(section)
            else:
                sections.add(section)
        return sections

    def _schedule_runtime_reload(self, changed: set[str]) -> None:
        if not changed or self.reload_runtime_services is None:
            return
        self._pending_runtime_reload.update(changed)
        if self._runtime_reload_task is None or self._runtime_reload_task.done():
            self._runtime_reload_task = asyncio.create_task(self._run_runtime_reload_queue())

    async def _run_runtime_reload_queue(self) -> None:
        while self._pending_runtime_reload:
            changed = set(self._pending_runtime_reload)
            self._pending_runtime_reload.clear()
            reload_runtime_services = self.reload_runtime_services
            if reload_runtime_services is None:
                continue
            try:
                await reload_runtime_services(changed)
                logger.info("Settings runtime reload completed for sections: %s", sorted(changed))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Settings runtime reload failed for sections: %s", sorted(changed))
        self._runtime_reload_task = None

    async def wait_for_runtime_reload_idle(self) -> None:
        task = self._runtime_reload_task
        if task is not None:
            await task

    async def _apply_runtime(self, runtime_updates: dict[str, object]) -> RuntimeApplyResult:
        if self.config is None:
            return {"runtime_applied": [], "runtime_changed": []}

        from .runtime_config import apply_runtime_config

        changed = apply_runtime_config(cast(RuntimeConfig, self.config), runtime_updates)
        self._schedule_runtime_reload(self._runtime_reload_sections(runtime_updates, changed))
        return {"runtime_applied": sorted(changed), "runtime_changed": sorted(changed)}

    def _apply_persisted_runtime_config(self) -> None:
        if self.config is None:
            return

        from .runtime_config import apply_runtime_config

        runtime_updates = self._validated_runtime_updates(self._validated_settings_dump())
        if runtime_updates:
            apply_runtime_config(cast(RuntimeConfig, self.config), runtime_updates)

    async def _commit_settings(self, next_settings: dict[str, object], runtime_updates: dict[str, object]) -> RuntimeApplyResult:
        async with self._store_lock:
            previous_settings = await asyncio.to_thread(self._validated_settings_dump)
            try:
                await asyncio.to_thread(self._replace_and_save_settings, next_settings)
            except Exception:
                await asyncio.to_thread(self.settings_store.replace, previous_settings)
                raise
        effective_runtime_updates = _changed_runtime_updates(previous_settings, runtime_updates)
        previous_dynamic = deepcopy(self.dynamic_config.config)
        try:
            _ = await self.dynamic_config.update_batch(runtime_updates)
            runtime_result = await self._apply_runtime(effective_runtime_updates)
            self._settings_snapshots.append(previous_settings)
        except Exception:
            async with self._store_lock:
                await asyncio.to_thread(self._replace_and_save_settings, previous_settings)
            self.dynamic_config.config = previous_dynamic
            raise
        return runtime_result

    def set_client_providers(self, llm_provider: ClientProvider, tts_provider: ClientProvider) -> None:
        self.llm_client_provider = llm_provider
        self.tts_client_provider = tts_provider

    def init_api(self) -> None:
        global _settings_api
        self._apply_persisted_runtime_config()
        _settings_api = self

    async def get_all_settings(self) -> PersistedSettingsSchema:
        settings = await self._validated_settings_dump_async()
        return PersistedSettingsSchema.model_validate(_mask_sensitive_settings(settings))

    async def get_setting(self, key: str) -> SettingValueResponse:
        value = await self._run_store_call(lambda: self.settings_store.get(key))
        if value is None:
            raise HTTPException(status_code=404, detail=f"Setting {key} not found")
        return SettingValueResponse(key=key, value=redact_sensitive_config_value(value, key))

    async def set_setting(self, key: str, value: object) -> SettingsMutationResponse:
        if key.rsplit(".", 1)[-1] in _SECRET_FIELD_NAMES and value == SETTINGS_SECRET_MASK:
            return SettingsMutationResponse(
                key=key,
                value=SETTINGS_SECRET_MASK,
                status="unchanged",
                runtime_applied=[],
                runtime_changed=[],
            )
        normalized = self._normalize_set_payload(key, value)
        base = await self._validated_settings_dump_async()
        try:
            next_settings = validate_persisted_settings(merge_settings(base, normalized)).model_dump()
            runtime_updates = self._validated_runtime_updates(normalized)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=validation_errors_to_detail(exc)) from exc
        runtime_result = await self._commit_settings(next_settings, runtime_updates)
        return SettingsMutationResponse(
            key=key,
            value=redact_sensitive_config_value(value, key),
            status="updated",
            runtime_applied=runtime_result["runtime_applied"],
            runtime_changed=runtime_result["runtime_changed"],
        )

    async def update_settings(self, updates: dict[str, object]) -> SettingsMutationResponse:
        base = await self._validated_settings_dump_async()
        normalized_updates = cast(dict[str, object], _drop_secret_placeholders(updates))
        try:
            next_settings = validate_persisted_settings(merge_settings(base, normalized_updates)).model_dump()
            runtime_updates = self._validated_runtime_updates(normalized_updates)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=validation_errors_to_detail(exc)) from exc
        runtime_result = await self._commit_settings(next_settings, runtime_updates)
        return SettingsMutationResponse(
            updated=len(updates),
            status="success",
            runtime_applied=runtime_result["runtime_applied"],
            runtime_changed=runtime_result["runtime_changed"],
        )

    async def delete_setting(self, key: str) -> SettingsMutationResponse:
        base = await self._validated_settings_dump_async()
        defaults = PersistedSettingsSchema().model_dump()
        try:
            value = self._value_for_key(defaults, key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Setting {key} not found or cannot be reset") from exc

        normalized = self._normalize_set_payload(key, value)
        try:
            next_settings = validate_persisted_settings(merge_settings(base, normalized)).model_dump()
            runtime_updates = self._validated_runtime_updates(normalized)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=validation_errors_to_detail(exc)) from exc
        runtime_result = await self._commit_settings(next_settings, runtime_updates)
        return SettingsMutationResponse(
            key=key,
            value=redact_sensitive_config_value(value, key),
            status="reset",
            runtime_applied=runtime_result["runtime_applied"],
            runtime_changed=runtime_result["runtime_changed"],
        )

    async def get_metadata(self) -> SettingsMetadataResponse:
        metadata = await self._run_store_call(self.settings_store.get_metadata)
        return SettingsMetadataResponse.model_validate(metadata)

    async def export_settings(self, filepath: str) -> SettingsExportResponse:
        relative_path = ensure_safe_relative_json_path(filepath)
        async with self._store_lock:
            def _export() -> Path:
                self.settings_store.replace(self._validated_settings_dump())
                return self.settings_store.export_managed(relative_path)

            target = await asyncio.to_thread(_export)
        return SettingsExportResponse(filepath=str(target), status="exported")

    async def import_settings(self, filepath: str) -> SettingsImportResponse:
        relative_path = ensure_safe_relative_json_path(filepath)
        source = cast(Path, await self._run_store_call(lambda: self.settings_store.import_managed(relative_path)))

        def _load_import_payload() -> object:
            with open(source, "r", encoding="utf-8") as f:
                return cast(object, json.load(f))

        loaded = await asyncio.to_thread(_load_import_payload)
        return await self.import_settings_payload(loaded, filepath=str(source))

    async def import_settings_payload(self, loaded: object, filepath: str = "inline-upload") -> SettingsImportResponse:
        if not isinstance(loaded, dict):
            raise HTTPException(status_code=422, detail="Settings import payload must be a JSON object")
        loaded_map = cast(dict[object, object], loaded)
        if not all(isinstance(key, str) for key in loaded_map):
            raise HTTPException(status_code=422, detail="Settings import payload must be a JSON object")
        raw_imported = cast(
            dict[str, object],
            _drop_secret_placeholders(normalize_inline_llm_import_payload(cast(dict[str, object], loaded_map))),
        )
        imported: dict[str, object] = merge_settings(await self._validated_settings_dump_async(), dict(raw_imported))
        try:
            next_settings = validate_persisted_settings(imported).model_dump()
            runtime_updates = self._validated_runtime_updates(imported)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=validation_errors_to_detail(exc)) from exc
        runtime_result = await self._commit_settings(next_settings, runtime_updates)
        return SettingsImportResponse(
            filepath=filepath,
            status="imported",
            runtime_applied=runtime_result["runtime_applied"],
            runtime_changed=runtime_result["runtime_changed"],
        )

    async def get_change_history(self, key: str | None = None, limit: int = 10) -> SettingsHistoryResponse:
        history = self.dynamic_config.get_history(key, limit)
        return SettingsHistoryResponse.model_validate({"history": history, "count": len(history)})

    async def rollback_changes(self, steps: int = 1) -> SettingsRollbackResponse:
        if steps <= 0:
            raise HTTPException(status_code=400, detail="Rollback steps must be positive")
        if steps <= len(self._settings_snapshots):
            previous_settings = cast(dict[str, object], await self._run_store_call(self.settings_store.get_all))
            target = cast(
                dict[str, object],
                _preserve_current_secrets(self._settings_snapshots[-steps], previous_settings),
            )
            del self._settings_snapshots[-steps:]
            previous_dynamic = deepcopy(self.dynamic_config.config)
            try:
                runtime_updates = self._validated_runtime_updates(target)
                await self._run_store_call(lambda: self._replace_and_save_settings(target))
                self.dynamic_config.config = deepcopy(runtime_updates)
                _ = await self._apply_runtime(runtime_updates)
                return SettingsRollbackResponse(steps=steps, status="rolled_back")
            except Exception:
                await self._run_store_call(lambda: self._replace_and_save_settings(previous_settings))
                self.dynamic_config.config = previous_dynamic
                raise
        if self.dynamic_config.rollback(steps):
            current_settings = cast(dict[str, object], await self._run_store_call(self.settings_store.get_all))
            rolled_back = cast(
                dict[str, object],
                _preserve_current_secrets(self.dynamic_config.get_all(), current_settings),
            )
            next_settings = validate_persisted_settings(rolled_back).model_dump()
            await self._run_store_call(lambda: self._replace_and_save_settings(next_settings))
            return SettingsRollbackResponse(steps=steps, status="rolled_back")
        raise HTTPException(status_code=400, detail=f"Cannot rollback {steps} steps")

    async def clear_history(self) -> SettingsMutationResponse:
        self.dynamic_config.clear_history()
        return SettingsMutationResponse(status="history_cleared")

    async def test_llm_connection(self) -> dict[str, object]:
        llm_client = self.llm_client_provider() if self.llm_client_provider is not None else None
        if not llm_client:
            return {"ok": False, "message": "LLM client not initialized"}
        return await llm_client.test_connection()

    async def get_llm_status(self) -> dict[str, object]:
        llm_client = self.llm_client_provider() if self.llm_client_provider is not None else None
        if not llm_client:
            return {
                "available": False,
                "preconnect_running": False,
                "message": "LLM client not initialized",
                "last_preconnect_error": "LLM client not initialized",
            }
        snapshot_provider = getattr(llm_client, "status_snapshot", None)
        if callable(snapshot_provider):
            try:
                snapshot = snapshot_provider()
            except Exception as exc:
                return {
                    "available": False,
                    "preconnect_running": False,
                    "message": f"LLM status error: {exc}",
                    "last_preconnect_error": f"LLM status error: {exc}",
                }
            if isinstance(snapshot, dict):
                return cast(dict[str, object], snapshot)
        return {
            "available": True,
            "preconnect_running": False,
            "message": "LLM preconnect status unavailable",
            "last_preconnect_error": None,
        }

    async def list_llm_models(self, request: dict[str, object]) -> dict[str, object]:
        settings = await self._validated_settings_dump_async()
        llm_settings = cast(dict[str, object], settings.get("llm", {}))
        raw_base_url = str(request.get("base_url") if request.get("base_url") is not None else llm_settings.get("base_url", ""))
        provider = normalize_llm_provider(request.get("provider") if request.get("provider") is not None else llm_settings.get("provider", ""), raw_base_url)
        base_url = normalize_llm_base_url(raw_base_url, provider)
        requested_api_key = request.get("api_key")
        api_key = str(
            llm_settings.get("api_key", "")
            if requested_api_key in {None, SETTINGS_SECRET_MASK}
            else requested_api_key
        )
        timeout_value = request.get("timeout") if request.get("timeout") is not None else llm_settings.get("timeout", 30.0)

        if not base_url:
            return {"ok": False, "models": [], "message": "LLM Base URL is required"}

        try:
            timeout = float(str(timeout_value))
        except (TypeError, ValueError):
            timeout = 30.0

        try:
            models = await fetch_available_models(base_url, api_key, timeout, provider)
        except ValueError as exc:
            return {"ok": False, "models": [], "message": str(exc)}
        except httpx.HTTPStatusError as exc:
            body_text = exc.response.text[:200] if exc.response.text else ""
            return {
                "ok": False,
                "models": [],
                "message": f"LLM API {exc.response.status_code}: {body_text}",
            }
        except httpx.RequestError as exc:
            return {"ok": False, "models": [], "message": f"LLM request failed: {exc}"}

        return {
            "ok": True,
            "models": models,
            "count": len(models),
            "message": "Models loaded" if models else "No models returned by upstream",
        }

    async def test_tts_connection(self) -> dict[str, object]:
        tts_client = self.tts_client_provider() if self.tts_client_provider is not None else None
        if not tts_client:
            return {"ok": False, "message": "TTS client not initialized"}
        return await tts_client.test_connection()

    async def warmup_tts(self) -> dict[str, object]:
        tts_client = self.tts_client_provider() if self.tts_client_provider is not None else None
        if not tts_client:
            return {
                "ok": False,
                "queued": False,
                "message": "TTS client not initialized",
                "runtime": await self.get_tts_status(),
            }

        warmup = getattr(tts_client, "warmup", None)
        if not callable(warmup):
            return {
                "ok": False,
                "queued": False,
                "message": "TTS warmup is not supported by the active TTS client",
                "runtime": await self.get_tts_status(),
            }

        try:
            warmup_async = cast(Callable[..., Awaitable[bool]], warmup)
            queued = await warmup_async(background=True)
        except Exception as exc:
            return {
                "ok": False,
                "queued": False,
                "message": f"TTS warmup failed: {exc}",
                "runtime": await self.get_tts_status(),
            }

        runtime = await self.get_tts_status()
        return {
            "ok": bool(queued),
            "queued": bool(queued),
            "message": "TTS warmup queued" if queued else "TTS warmup was not queued",
            "runtime": runtime,
        }

    async def get_tts_status(self) -> dict[str, object]:
        tts_client = self.tts_client_provider() if self.tts_client_provider is not None else None
        if not tts_client:
            return {
                "provider": "genie-tts",
                "available": False,
                "loading": False,
                "warming_up": False,
                "warmup_running": False,
                "warmup_done": False,
                "message": "TTS client not initialized",
                "last_error": "TTS client not initialized",
                "capabilities": resolve_tts_provider_capabilities("genie-tts"),
            }
        snapshot_provider = getattr(tts_client, "status_snapshot", None)
        if callable(snapshot_provider):
            try:
                snapshot = snapshot_provider()
            except Exception as exc:
                return {
                    "provider": "genie-tts",
                    "available": False,
                    "loading": False,
                    "warming_up": False,
                    "warmup_running": False,
                    "warmup_done": False,
                    "message": f"TTS status error: {exc}",
                    "last_error": f"TTS status error: {exc}",
                    "capabilities": resolve_tts_provider_capabilities("genie-tts"),
                }
            if isinstance(snapshot, dict):
                return cast(dict[str, object], snapshot)
        return {
            "provider": "genie-tts",
            "available": True,
            "loading": False,
            "warming_up": False,
            "warmup_running": False,
            "warmup_done": False,
            "message": "TTS status unavailable",
            "last_error": None,
            "capabilities": resolve_tts_provider_capabilities("genie-tts"),
        }

    async def discover_local_services(self) -> dict[str, object]:
        return await discover_local_runtime_candidates()


SettingsAPIDependency = Annotated[SettingsAPI, Depends(get_settings_api)]
SettingBody = Annotated[object, Body(...)]


def _settings_admin_token(api: SettingsAPI) -> str:
    summary = getattr(api.config, "summary", None)
    return str(getattr(summary, "admin_token", "") or "").strip()


def _require_settings_admin(api: SettingsAPI, authorization: str | None):
    return require_bearer_token(authorization, _settings_admin_token(api))


@router.get("/", response_model=PersistedSettingsSchema)
async def get_all_settings(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.get_all_settings()


@router.get("/metadata", response_model=SettingsMetadataResponse)
async def get_metadata(api: SettingsAPIDependency):
    return await api.get_metadata()


@router.get("/history", response_model=SettingsHistoryResponse)
async def get_history(api: SettingsAPIDependency, key: str | None = None, limit: int = 10, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.get_change_history(key, limit)


@router.get("/export")
async def export_current_settings(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    settings = await api.get_all_settings()
    return JSONResponse(
        content=settings.model_dump(),
        headers={"Content-Disposition": 'attachment; filename="yuizaki-llm-settings.json"'},
    )


@router.post("/import", response_model=SettingsImportResponse)
async def import_settings_payload(payload: dict[str, object], api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.import_settings_payload(payload)


@router.delete("/history", response_model=SettingsMutationResponse)
async def clear_history(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.clear_history()


@router.post("/test/llm")
async def test_llm_connection(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.test_llm_connection()


@router.post("/llm/models")
async def list_llm_models(request: dict[str, object], api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.list_llm_models(request)


@router.get("/llm/status")
async def get_llm_status(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.get_llm_status()


@router.post("/test/tts")
async def test_tts_connection(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.test_tts_connection()


@router.get("/tts/status")
async def get_tts_status(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.get_tts_status()


@router.post("/tts/warmup")
async def warmup_tts(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.warmup_tts()


@router.get("/local-discovery")
async def discover_local_services(api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.discover_local_services()


@router.post("/rollback", response_model=SettingsRollbackResponse)
async def rollback_changes(api: SettingsAPIDependency, steps: int = 1, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.rollback_changes(steps)


@router.get("/{key}", response_model=SettingValueResponse)
async def get_setting(key: str, api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.get_setting(key)


@router.post("/{key}", response_model=SettingsMutationResponse)
async def set_setting(key: str, value: SettingBody, api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.set_setting(key, value)


@router.patch("/", response_model=SettingsMutationResponse)
async def update_settings(updates: dict[str, object], api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.update_settings(updates)


@router.delete("/{key}", response_model=SettingsMutationResponse)
async def delete_setting(key: str, api: SettingsAPIDependency, authorization: str | None = Header(default=None)):
    auth_error = _require_settings_admin(api, authorization)
    if auth_error is not None:
        return auth_error
    return await api.delete_setting(key)
