# pyright: reportUnusedFunction=false

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse


def _custom_stdio_mcp_enabled() -> bool:
    return os.getenv("YUIZAKI_ALLOW_CUSTOM_MCP_STDIO", "").strip().lower() in {"1", "true", "yes", "on"}


def create_system_router(
    health_handler: Callable[[], Any],
    readiness_handler: Callable[[], Any],
    system_status_handler: Callable[[], Any],
    onboarding_readiness_state_handler: Callable[[], Any] | None = None,
    onboarding_readiness_run_handler: Callable[[list[str] | None], Any] | None = None,
    onboarding_readiness_retry_handler: Callable[[str, list[str] | None], Any] | None = None,
    onboarding_readiness_cancel_handler: Callable[[str], Any] | None = None,
    onboarding_readiness_action_handler: Callable[[str], Any] | None = None,
    heartbeat_status_handler: Callable[[], Any] | None = None,
    companion_runtime_handler: Callable[[int], Any] | None = None,
    companion_opportunity_outcome_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    heartbeat_opportunity_accept_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    heartbeat_goal_cancel_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    proactive_settings_get_handler: Callable[[], Any] | None = None,
    proactive_settings_patch_handler: Callable[[dict[str, Any]], Any] | None = None,
    activity_frames_list_handler: Callable[[int], Any] | None = None,
    activity_frames_rebuild_handler: Callable[[dict[str, Any]], Any] | None = None,
    activity_frame_delete_handler: Callable[[str], Any] | None = None,
    proactive_feedback_handler: Callable[[dict[str, Any]], Any] | None = None,
    proactive_feedback_summary_handler: Callable[[], Any] | None = None,
    capabilities_state_handler: Callable[[], Any] | None = None,
    provider_registry_handler: Callable[[], Any] | None = None,
    connector_registry_handler: Callable[[], Any] | None = None,
    platform_matrix_handler: Callable[[], Any] | None = None,
    disable_connector_handler: Callable[[str], Any] | None = None,
    orchestration_state_handler: Callable[[], Any] | None = None,
    active_workspace_handler: Callable[[dict[str, Any]], Any] | None = None,
    permissions_handler: Callable[[], Any] | None = None,
    revoke_permission_handler: Callable[[str], Any] | None = None,
    clear_permissions_handler: Callable[[], Any] | None = None,
    schedules_handler: Callable[[], Any] | None = None,
    create_once_schedule_handler: Callable[[str, str, int], Any] | None = None,
    create_interval_schedule_handler: Callable[[str, str, int], Any] | None = None,
    remove_schedule_handler: Callable[[str], Any] | None = None,
    toggle_schedule_handler: Callable[[str, bool], Any] | None = None,
    run_schedule_now_handler: Callable[[str], Any] | None = None,
    cancel_schedule_handler: Callable[[str], Any] | None = None,
    agent_trace_handler: Callable[[], Any] | None = None,
    experience_metrics_handler: Callable[[], Any] | None = None,
    voice_diagnostics_handler: Callable[[], Any] | None = None,
    voice_diagnostics_begin_handler: Callable[[dict[str, Any]], Any] | None = None,
    voice_diagnostics_comfort_handler: Callable[[dict[str, Any]], Any] | None = None,
    voice_diagnostics_comfort_signal_handler: Callable[[dict[str, Any]], Any] | None = None,
    voice_diagnostics_sample_handler: Callable[[dict[str, Any]], Any] | None = None,
    product_metrics_consent_handler: Callable[[], Any] | None = None,
    product_metrics_consent_patch_handler: Callable[[bool], Any] | None = None,
    mcp_state_handler: Callable[[], Any] | None = None,
    toggle_mcp_handler: Callable[[str, bool], Any] | None = None,
    add_mcp_handler: Callable[[str, str, str, bool, str | None, list[str] | None, dict[str, str] | None, dict[str, str] | None], Any] | None = None,
    install_mcp_preset_handler: Callable[[str], Any] | None = None,
    remove_mcp_handler: Callable[[str], Any] | None = None,
    refresh_mcp_handler: Callable[[str], Any] | None = None,
    agent_plugin_state_handler: Callable[[], Any] | None = None,
    toggle_agent_plugin_handler: Callable[[str, bool], Any] | None = None,
    update_agent_plugin_config_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    imported_skills_state_handler: Callable[[], Any] | None = None,
    save_imported_skills_handler: Callable[[list[dict[str, Any]]], Any] | None = None,
    remove_imported_skills_handler: Callable[[list[str]], Any] | None = None,
    stream_status_handler: Callable[[], Any] | None = None,
    stream_moderation_handler: Callable[[], Any] | None = None,
    stream_moderation_update_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_preview_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_probe_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_obs_configure_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_obs_profiles_handler: Callable[[], Any] | None = None,
    stream_events_handler: Callable[[int], Any] | None = None,
    stream_actions_handler: Callable[[int], Any] | None = None,
    stream_event_enqueue_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_takeover_handler: Callable[[bool], Any] | None = None,
    stream_execute_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_twitch_eventsub_handler: Callable[[bytes, Mapping[str, Any]], Any] | None = None,
    stream_twitch_irc_handler: Callable[[str], Any] | None = None,
    stream_twitch_reconfigure_handler: Callable[..., Any] | None = None,
    stream_twitch_probe_handler: Callable[[], Any] | None = None,
    stream_twitch_subscriptions_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_twitch_connect_handler: Callable[[], Any] | None = None,
    stream_twitch_disconnect_handler: Callable[[], Any] | None = None,
    stream_twitch_tick_handler: Callable[[], Any] | None = None,
    stream_drafts_handler: Callable[[int], Any] | None = None,
    stream_draft_generate_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_draft_consume_handler: Callable[[dict[str, Any]], Any] | None = None,
    stream_draft_consumer_status_handler: Callable[[], Any] | None = None,
    stream_draft_consumer_toggle_handler: Callable[[dict[str, Any]], Any] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["system"])

    async def _call_handler(handler: Callable[..., Any], *args: Any, offload: bool = False) -> Any:
        if offload and not inspect.iscoroutinefunction(handler):
            result = await asyncio.to_thread(handler, *args)
        else:
            result = handler(*args)
        if inspect.isawaitable(result):
            return await result
        return result

    def _handler_accepts_mcp_headers(handler: Callable[..., Any]) -> bool:
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            return True
        parameters = list(signature.parameters.values())
        if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
            return True
        positional_parameters = [
            parameter
            for parameter in parameters
            if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        return len(positional_parameters) >= 8

    def _validate_mcp_registration(payload: dict[str, Any]) -> tuple[str, str, str, bool, str | None, list[str], dict[str, str] | None, dict[str, str] | None]:
        name = str(payload.get("name") or "").strip()
        base_url = str(payload.get("base_url") or "").strip()
        transport = str(payload.get("transport") or "http").strip().lower()
        command = str(payload.get("command") or "").strip() or None
        args = [str(item) for item in (payload.get("args") or []) if item is not None]
        raw_env = payload.get("env")
        env: dict[str, str] | None = None
        if isinstance(raw_env, dict):
            env = {str(key): str(value) for key, value in raw_env.items() if str(key).strip()}
        raw_headers = payload.get("headers")
        headers: dict[str, str] | None = None
        if isinstance(raw_headers, dict):
            headers = {str(key): str(value) for key, value in raw_headers.items() if str(key).strip()}

        if not name:
            raise HTTPException(status_code=422, detail="MCP server name is required")
        if transport not in {"http", "sse", "stdio", "streamable_http"}:
            raise HTTPException(status_code=422, detail="MCP transport must be one of: http, sse, stdio, streamable_http")
        if transport in {"http", "sse", "streamable_http"}:
            if not base_url:
                raise HTTPException(status_code=422, detail="MCP base_url is required for http/sse transports")
            parsed_base_url = urlparse(base_url)
            if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
                raise HTTPException(status_code=422, detail="MCP base_url must be an http(s) URL")
        if transport == "stdio":
            if not command:
                raise HTTPException(status_code=422, detail="MCP command is required for stdio transport")
            if not _custom_stdio_mcp_enabled():
                raise HTTPException(
                    status_code=403,
                    detail="Custom stdio MCP registration is disabled; install a preset or set YUIZAKI_ALLOW_CUSTOM_MCP_STDIO=true",
                )

        return name, base_url, transport, bool(payload.get("enabled", True)), command, args, env, headers

    def _coerce_int(payload: dict[str, Any], key: str, default: int) -> int:
        raw_value = payload.get(key, default)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{key} must be an integer") from None

    def _validate_schedule_fields(payload: dict[str, Any], default_name: str) -> tuple[str, str]:
        name = str(payload.get("name") or default_name).strip() or default_name
        prompt = str(payload.get("prompt") or "").strip()
        if len(name) > 80:
            raise HTTPException(status_code=422, detail="Schedule name must be 80 characters or less")
        if not prompt:
            raise HTTPException(status_code=422, detail="Schedule prompt is required")
        if len(prompt) > 8000:
            raise HTTPException(status_code=422, detail="Schedule prompt must be 8000 characters or less")
        return name, prompt

    def _validate_once_schedule(payload: dict[str, Any]) -> tuple[str, str, int]:
        name, prompt = _validate_schedule_fields(payload, "once-task")
        run_after_seconds = _coerce_int(payload, "run_after_seconds", 60)
        if run_after_seconds < 5 or run_after_seconds > 86400:
            raise HTTPException(status_code=422, detail="run_after_seconds must be between 5 and 86400")
        return name, prompt, run_after_seconds

    def _validate_interval_schedule(payload: dict[str, Any]) -> tuple[str, str, int]:
        name, prompt = _validate_schedule_fields(payload, "interval-task")
        interval_seconds = _coerce_int(payload, "interval_seconds", 300)
        if interval_seconds < 30 or interval_seconds > 86400:
            raise HTTPException(status_code=422, detail="interval_seconds must be between 30 and 86400")
        return name, prompt, interval_seconds

    def _validate_imported_skill_items(payload: Any) -> list[dict[str, Any]]:
        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise HTTPException(status_code=422, detail="Skill items must be a list")
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise HTTPException(status_code=422, detail="Each Skill item must be an object")
            items.append(item)
        if len(items) > 500:
            raise HTTPException(status_code=422, detail="Imported Skill list must contain 500 items or fewer")
        return items

    def _validate_imported_skill_ids(payload: Any) -> list[str]:
        raw_ids = payload.get("ids") if isinstance(payload, dict) else payload
        if not isinstance(raw_ids, list):
            raise HTTPException(status_code=422, detail="Skill ids must be a list")
        ids = [str(item).strip() for item in raw_ids if str(item).strip()]
        if not ids:
            raise HTTPException(status_code=422, detail="At least one Skill id is required")
        if len(ids) > 500:
            raise HTTPException(status_code=422, detail="Skill id list must contain 500 ids or fewer")
        return ids

    @router.get("/health")
    async def health():
        return await _call_handler(health_handler)

    @router.get("/api/readiness")
    async def readiness():
        return await _call_handler(readiness_handler)

    def _strict_payload(payload: dict[str, Any], allowed: set[str]) -> None:
        extra = set(payload) - allowed
        if extra:
            raise HTTPException(status_code=422, detail=f"Unknown fields: {', '.join(sorted(extra))}")

    def _probe_ids(payload: dict[str, Any]) -> list[str] | None:
        value = payload.get("probeIds")
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise HTTPException(status_code=422, detail="probeIds must be a list of strings")
        return value

    if onboarding_readiness_state_handler is not None:
        @router.get("/api/system/onboarding/readiness")
        async def onboarding_readiness_state():
            return await _call_handler(onboarding_readiness_state_handler)

    if onboarding_readiness_run_handler is not None:
        @router.post("/api/system/onboarding/readiness/run")
        async def onboarding_readiness_run(payload: dict[str, Any] | None = None):
            body = payload or {}
            _strict_payload(body, {"probeIds"})
            try:
                return await _call_handler(onboarding_readiness_run_handler, _probe_ids(body))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if onboarding_readiness_retry_handler is not None:
        @router.post("/api/system/onboarding/readiness/retry")
        async def onboarding_readiness_retry(payload: dict[str, Any]):
            _strict_payload(payload, {"runId", "probeIds"})
            run_id = payload.get("runId")
            if not isinstance(run_id, str) or not run_id.strip():
                raise HTTPException(status_code=422, detail="runId is required")
            try:
                return await _call_handler(onboarding_readiness_retry_handler, run_id, _probe_ids(payload))
            except LookupError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if onboarding_readiness_cancel_handler is not None:
        @router.post("/api/system/onboarding/readiness/cancel")
        async def onboarding_readiness_cancel(payload: dict[str, Any]):
            _strict_payload(payload, {"runId"})
            run_id = payload.get("runId")
            if not isinstance(run_id, str) or not run_id.strip():
                raise HTTPException(status_code=422, detail="runId is required")
            try:
                return await _call_handler(onboarding_readiness_cancel_handler, run_id)
            except LookupError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    if onboarding_readiness_action_handler is not None:
        @router.post("/api/system/onboarding/readiness/action")
        async def onboarding_readiness_action(payload: dict[str, Any]):
            _strict_payload(payload, {"actionId"})
            action_id = payload.get("actionId")
            if not isinstance(action_id, str) or not action_id.strip():
                raise HTTPException(status_code=422, detail="actionId is required")
            if action_id != "mcp.refresh_existing":
                raise HTTPException(status_code=422, detail="unknown readiness actionId")
            try:
                return await _call_handler(onboarding_readiness_action_handler, action_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/system/status")
    async def system_status():
        return await _call_handler(system_status_handler)

    if heartbeat_status_handler is not None:
        @router.get("/api/system/heartbeat")
        async def heartbeat_status():
            return await _call_handler(heartbeat_status_handler, offload=True)

    if companion_runtime_handler is not None:
        @router.get("/api/system/companion-runtime")
        async def companion_runtime_status(limit: int = 8):
            return await _call_handler(companion_runtime_handler, limit, offload=True)

    if companion_opportunity_outcome_handler is not None:
        @router.post("/api/system/companion-runtime/opportunities/outcome/{job_id:path}")
        async def companion_opportunity_outcome(job_id: str, payload: dict[str, Any]):
            return await _call_handler(companion_opportunity_outcome_handler, job_id, payload, offload=True)

    if heartbeat_opportunity_accept_handler is not None:
        @router.post("/api/system/heartbeat/opportunities/{job_id:path}/accept")
        async def heartbeat_opportunity_accept(job_id: str, payload: dict[str, Any]):
            return await _call_handler(heartbeat_opportunity_accept_handler, job_id, payload)

    if heartbeat_goal_cancel_handler is not None:
        @router.post("/api/system/heartbeat/goals/{goal_id:path}/cancel")
        async def heartbeat_goal_cancel(goal_id: str, payload: dict[str, Any] | None = None):
            return await _call_handler(heartbeat_goal_cancel_handler, goal_id, payload or {}, offload=True)

    if proactive_settings_get_handler is not None:
        @router.get("/api/system/proactive/settings")
        async def proactive_settings_get():
            return await _call_handler(proactive_settings_get_handler, offload=True)

    if proactive_settings_patch_handler is not None:
        @router.patch("/api/system/proactive/settings")
        async def proactive_settings_patch(payload: dict[str, Any]):
            try:
                return await _call_handler(proactive_settings_patch_handler, payload, offload=True)
            except LookupError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if activity_frames_list_handler is not None:
        @router.get("/api/system/activity-frames")
        async def activity_frames_list(limit: int = 50):
            if not 1 <= limit <= 200:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
            return await _call_handler(activity_frames_list_handler, limit, offload=True)

    if activity_frames_rebuild_handler is not None:
        @router.post("/api/system/activity-frames/rebuild")
        async def activity_frames_rebuild(
            payload: dict[str, Any] | None = None,
        ):
            try:
                return await _call_handler(activity_frames_rebuild_handler, payload or {}, offload=True)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if activity_frame_delete_handler is not None:
        @router.delete("/api/system/activity-frames/{frame_id:path}")
        async def activity_frame_delete(frame_id: str):
            try:
                return await _call_handler(activity_frame_delete_handler, frame_id, offload=True)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if proactive_feedback_handler is not None:
        @router.post("/api/system/proactive/feedback")
        async def proactive_feedback(payload: dict[str, Any]):
            try:
                return await _call_handler(proactive_feedback_handler, payload, offload=True)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if proactive_feedback_summary_handler is not None:
        @router.get("/api/system/proactive/feedback-summary")
        async def proactive_feedback_summary():
            return await _call_handler(proactive_feedback_summary_handler, offload=True)

    if capabilities_state_handler is not None:
        @router.get("/api/system/capabilities")
        async def capabilities_state():
            return await _call_handler(capabilities_state_handler, offload=True)

    if provider_registry_handler is not None:
        @router.get("/api/system/providers")
        async def provider_registry_state():
            return await _call_handler(provider_registry_handler, offload=True)

    if voice_diagnostics_handler is not None:
        @router.get("/api/system/voice-diagnostics")
        async def voice_diagnostics_state():
            return await _call_handler(voice_diagnostics_handler, offload=True)

    if voice_diagnostics_begin_handler is not None:
        @router.post("/api/system/voice-diagnostics/run")
        async def voice_diagnostics_begin(payload: dict[str, Any] | None = None):
            body = payload or {}
            _strict_payload(body, {"run_id"})
            try:
                return await _call_handler(voice_diagnostics_begin_handler, body, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if voice_diagnostics_comfort_handler is not None:
        @router.post("/api/system/voice-diagnostics/comfort")
        async def voice_diagnostics_comfort(payload: dict[str, Any]):
            _strict_payload(
                payload,
                {
                    "scenario",
                    "stop_audio_latency_ms",
                    "interrupt_ack_latency_ms",
                    "false_interruption",
                    "first_audio_latency_ms",
                    "continuous_turn_completed",
                    "run_id",
                },
            )
            try:
                return await _call_handler(voice_diagnostics_comfort_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if voice_diagnostics_comfort_signal_handler is not None:
        @router.post("/api/system/voice-diagnostics/comfort-signal")
        async def voice_diagnostics_comfort_signal(payload: dict[str, Any]):
            _strict_payload(
                payload,
                {"signal", "source", "confidence", "duration_ms", "run_id"},
            )
            try:
                return await _call_handler(voice_diagnostics_comfort_signal_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if voice_diagnostics_sample_handler is not None:
        @router.post("/api/system/voice-diagnostics/sample")
        async def voice_diagnostics_sample(payload: dict[str, Any]):
            _strict_payload(
                payload,
                {
                    "stage",
                    "latency_ms",
                    "ok",
                    "provider",
                    "error_kind",
                    "recovered",
                    "recovery_latency_ms",
                    "playback_underruns",
                    "run_id",
                },
            )
            try:
                return await _call_handler(voice_diagnostics_sample_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if connector_registry_handler is not None:
        @router.get("/api/system/connectors")
        async def connector_registry_state():
            return await _call_handler(connector_registry_handler, offload=True)

    if platform_matrix_handler is not None:
        @router.get("/api/system/platforms")
        async def platform_matrix_state():
            return await _call_handler(platform_matrix_handler, offload=True)

    if disable_connector_handler is not None:
        @router.post("/api/system/connectors/{connector_id:path}/disable")
        async def disable_connector(connector_id: str):
            return await _call_handler(disable_connector_handler, connector_id, offload=True)

    if orchestration_state_handler is not None:
        @router.get("/api/system/orchestration")
        async def orchestration_state():
            return await _call_handler(orchestration_state_handler, offload=True)

    if active_workspace_handler is not None:
        @router.post("/api/system/active-workspace")
        async def set_active_workspace(payload: dict[str, Any]):
            return await _call_handler(active_workspace_handler, payload, offload=True)

    if permissions_handler is not None:
        @router.get("/api/system/permissions")
        async def permissions_state():
            return await _call_handler(permissions_handler, offload=True)

    if revoke_permission_handler is not None:
        @router.delete("/api/system/permissions/{tool_name:path}")
        async def revoke_permission(tool_name: str):
            return await _call_handler(revoke_permission_handler, tool_name, offload=True)

    if clear_permissions_handler is not None:
        @router.delete("/api/system/permissions")
        async def clear_permissions():
            return await _call_handler(clear_permissions_handler, offload=True)

    if schedules_handler is not None:
        @router.get("/api/system/schedules")
        async def schedules_state():
            return await _call_handler(schedules_handler, offload=True)

    if create_once_schedule_handler is not None:
        @router.post("/api/system/schedules/once")
        async def create_once_schedule(payload: dict[str, Any]):
            name, prompt, run_after_seconds = _validate_once_schedule(payload)
            return await _call_handler(create_once_schedule_handler, name, prompt, run_after_seconds, offload=True)

    if create_interval_schedule_handler is not None:
        @router.post("/api/system/schedules/interval")
        async def create_interval_schedule(payload: dict[str, Any]):
            name, prompt, interval_seconds = _validate_interval_schedule(payload)
            return await _call_handler(create_interval_schedule_handler, name, prompt, interval_seconds, offload=True)

    if remove_schedule_handler is not None:
        @router.delete("/api/system/schedules/{task_id:path}")
        async def remove_schedule(task_id: str):
            return await _call_handler(remove_schedule_handler, task_id, offload=True)

    if toggle_schedule_handler is not None:
        @router.post("/api/system/schedules/{task_id:path}/toggle")
        async def toggle_schedule(task_id: str, payload: dict[str, Any]):
            return await _call_handler(toggle_schedule_handler, task_id, bool(payload.get("enabled", True)), offload=True)

    if run_schedule_now_handler is not None:
        @router.post("/api/system/schedules/{task_id:path}/run")
        async def run_schedule_now(task_id: str):
            return await _call_handler(run_schedule_now_handler, task_id, offload=True)

    if cancel_schedule_handler is not None:
        @router.post("/api/system/schedules/{task_id:path}/cancel")
        async def cancel_schedule(task_id: str):
            return await _call_handler(cancel_schedule_handler, task_id, offload=True)

    if agent_trace_handler is not None:
        @router.get("/api/system/agent-trace")
        async def agent_trace_state():
            return await _call_handler(agent_trace_handler, offload=True)

    if experience_metrics_handler is not None:
        @router.get("/api/system/experience-metrics")
        async def experience_metrics_state():
            return await _call_handler(experience_metrics_handler, offload=True)

    if product_metrics_consent_handler is not None:
        @router.get("/api/system/product-metrics/consent")
        async def product_metrics_consent():
            return await _call_handler(product_metrics_consent_handler, offload=True)

    if product_metrics_consent_patch_handler is not None:
        @router.patch("/api/system/product-metrics/consent")
        async def product_metrics_consent_patch(
            payload: dict[str, Any],
        ):
            _strict_payload(payload, {"consented"})
            consented = payload.get("consented")
            if not isinstance(consented, bool):
                raise HTTPException(status_code=422, detail="consented must be a boolean")
            try:
                return await _call_handler(product_metrics_consent_patch_handler, consented, offload=True)
            except (OSError, RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=409, detail="product metrics consent could not be persisted") from exc

    if mcp_state_handler is not None:
        @router.get("/api/system/mcp")
        async def mcp_state():
            return await _call_handler(mcp_state_handler, offload=True)

    if toggle_mcp_handler is not None:
        @router.post("/api/system/mcp/{server_name:path}/toggle")
        async def toggle_mcp(server_name: str, payload: dict[str, Any]):
            return await _call_handler(toggle_mcp_handler, server_name, bool(payload.get("enabled", True)), offload=True)

    if add_mcp_handler is not None:
        @router.post("/api/system/mcp")
        async def add_mcp(payload: dict[str, Any]):
            name, base_url, transport, enabled, command, args, env, headers = _validate_mcp_registration(payload)
            if not _handler_accepts_mcp_headers(add_mcp_handler):
                return await _call_handler(add_mcp_handler, name, base_url, transport, enabled, command, args, env, offload=True)
            return await _call_handler(add_mcp_handler, name, base_url, transport, enabled, command, args, env, headers, offload=True)

    if install_mcp_preset_handler is not None:
        @router.post("/api/system/mcp/presets/{preset_id:path}/install")
        async def install_mcp_preset(preset_id: str):
            return await _call_handler(install_mcp_preset_handler, preset_id, offload=True)

    if remove_mcp_handler is not None:
        @router.delete("/api/system/mcp/{server_name:path}")
        async def remove_mcp(server_name: str):
            return await _call_handler(remove_mcp_handler, server_name, offload=True)

    if refresh_mcp_handler is not None:
        @router.post("/api/system/mcp/{server_name:path}/refresh")
        async def refresh_mcp(server_name: str):
            return await _call_handler(refresh_mcp_handler, server_name, offload=True)

    if agent_plugin_state_handler is not None:
        @router.get("/api/system/agent-plugins")
        async def agent_plugin_state():
            return await _call_handler(agent_plugin_state_handler, offload=True)

    if toggle_agent_plugin_handler is not None:
        @router.post("/api/system/agent-plugins/{plugin_id:path}/toggle")
        async def toggle_agent_plugin(plugin_id: str, payload: dict[str, Any]):
            return await _call_handler(toggle_agent_plugin_handler, plugin_id, bool(payload.get("enabled", True)), offload=True)

    if update_agent_plugin_config_handler is not None:
        @router.post("/api/system/agent-plugins/{plugin_id:path}/config")
        async def update_agent_plugin_config(plugin_id: str, payload: dict[str, Any]):
            return await _call_handler(update_agent_plugin_config_handler, plugin_id, payload, offload=True)

    if imported_skills_state_handler is not None:
        @router.get("/api/system/skills/imported")
        async def imported_skills_state():
            return await _call_handler(imported_skills_state_handler, offload=True)

    if save_imported_skills_handler is not None:
        @router.put("/api/system/skills/imported")
        async def save_imported_skills(payload: dict[str, Any]):
            items = _validate_imported_skill_items(payload)
            return await _call_handler(save_imported_skills_handler, items, offload=True)

    if remove_imported_skills_handler is not None:
        @router.delete("/api/system/skills/imported")
        async def remove_imported_skills(payload: dict[str, Any]):
            ids = _validate_imported_skill_ids(payload)
            return await _call_handler(remove_imported_skills_handler, ids, offload=True)

    if stream_status_handler is not None:
        @router.get("/api/system/stream")
        async def stream_status():
            return await _call_handler(stream_status_handler, offload=True)

    if stream_moderation_handler is not None:
        @router.get("/api/system/stream/moderation")
        async def stream_moderation():
            return await _call_handler(stream_moderation_handler, offload=True)

    if stream_moderation_update_handler is not None:
        @router.patch("/api/system/stream/moderation")
        async def stream_moderation_update(payload: dict[str, Any]):
            _strict_payload(payload, {"enabled", "blockedTerms", "slowModeSeconds", "maxMessagesPerMinute"})
            try:
                return await _call_handler(stream_moderation_update_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    if stream_preview_handler is not None:
        @router.post("/api/system/stream/preview")
        async def stream_preview(payload: dict[str, Any]):
            _strict_payload(payload, {"action", "params"})
            try:
                return await _call_handler(stream_preview_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_probe_handler is not None:
        @router.post("/api/system/stream/probe")
        async def stream_probe(payload: dict[str, Any] | None = None):
            body = payload or {}
            _strict_payload(body, {"endpoint", "password"})
            try:
                return await _call_handler(stream_probe_handler, body, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_obs_configure_handler is not None:
        @router.put("/api/system/stream/obs")
        async def stream_obs_configure(payload: dict[str, Any]):
            _strict_payload(payload, {"endpoint", "password", "allowRemote", "clearPassword"})
            try:
                return await _call_handler(stream_obs_configure_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_obs_profiles_handler is not None:
        @router.get("/api/system/stream/obs/profiles")
        async def stream_obs_profiles():
            try:
                return await _call_handler(stream_obs_profiles_handler, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    if stream_events_handler is not None:
        @router.get("/api/system/stream/events")
        async def stream_events(limit: int = 50):
            if not 1 <= limit <= 100:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
            return await _call_handler(stream_events_handler, limit, offload=True)

    if stream_actions_handler is not None:
        @router.get("/api/system/stream/actions")
        async def stream_actions(limit: int = 50):
            if not 1 <= limit <= 100:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
            return await _call_handler(stream_actions_handler, limit, offload=True)

    if stream_event_enqueue_handler is not None:
        @router.post("/api/system/stream/events")
        async def stream_event_enqueue(payload: dict[str, Any]):
            _strict_payload(payload, {"kind", "text", "author"})
            try:
                return await _call_handler(stream_event_enqueue_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_takeover_handler is not None:
        @router.post("/api/system/stream/takeover")
        async def stream_takeover(payload: dict[str, Any]):
            _strict_payload(payload, {"enabled"})
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                raise HTTPException(status_code=422, detail="enabled must be a boolean")
            try:
                return await _call_handler(stream_takeover_handler, enabled, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_execute_handler is not None:
        @router.post("/api/system/stream/execute")
        async def stream_execute(payload: dict[str, Any]):
            _strict_payload(payload, {"requestId", "action", "confirmed", "params"})
            try:
                return await _call_handler(stream_execute_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    if stream_twitch_eventsub_handler is not None:
        @router.post("/api/system/stream/twitch/eventsub")
        async def stream_twitch_eventsub(request: Request):
            try:
                result = await _call_handler(
                    stream_twitch_eventsub_handler,
                    await request.body(),
                    dict(request.headers),
                    offload=True,
                )
            except ValueError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            if isinstance(result, dict) and isinstance(result.get("challenge"), str):
                return PlainTextResponse(result["challenge"], status_code=200)
            return JSONResponse(result)

    if stream_twitch_irc_handler is not None:
        @router.post("/api/system/stream/twitch/irc")
        async def stream_twitch_irc(payload: dict[str, Any]):
            _strict_payload(payload, {"line"})
            line = payload.get("line")
            if not isinstance(line, str) or not line.strip():
                raise HTTPException(status_code=422, detail="line is required")
            try:
                return await _call_handler(stream_twitch_irc_handler, line, offload=True)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_twitch_reconfigure_handler is not None:
        @router.post("/api/system/stream/twitch/reconfigure")
        async def stream_twitch_reconfigure():
            try:
                return await _call_handler(stream_twitch_reconfigure_handler, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        @router.put("/api/system/stream/twitch/config")
        async def stream_twitch_config(payload: dict[str, Any]):
            _strict_payload(payload, {
                "clientId", "eventsubSecret", "eventsubToken", "chatToken",
                "broadcasterId", "senderId", "moderatorId", "channel", "username",
                "eventsubCallbackUrl", "subscriptionProvider",
                "clearClientId", "clearEventsubSecret", "clearEventsubToken", "clearChatToken",
                "clearBroadcasterId", "clearSenderId", "clearModeratorId", "clearChannel",
                "clearUsername", "clearEventsubCallbackUrl", "clearSubscriptionProvider",
            })
            try:
                return await _call_handler(stream_twitch_reconfigure_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

    if stream_twitch_probe_handler is not None:
        @router.post("/api/system/stream/twitch/probe")
        async def stream_twitch_probe():
            try:
                return await _call_handler(stream_twitch_probe_handler, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_twitch_subscriptions_handler is not None:
        @router.put("/api/system/stream/twitch/subscriptions")
        async def stream_twitch_subscriptions(payload: dict[str, Any]):
            _strict_payload(payload, {"subscriptions"})
            try:
                return await _call_handler(stream_twitch_subscriptions_handler, payload, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_twitch_connect_handler is not None:
        @router.post("/api/system/stream/twitch/connect")
        async def stream_twitch_connect():
            try:
                return await _call_handler(stream_twitch_connect_handler, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_twitch_disconnect_handler is not None:
        @router.post("/api/system/stream/twitch/disconnect")
        async def stream_twitch_disconnect():
            try:
                return await _call_handler(stream_twitch_disconnect_handler, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_twitch_tick_handler is not None:
        @router.post("/api/system/stream/twitch/tick")
        async def stream_twitch_tick():
            try:
                return await _call_handler(stream_twitch_tick_handler, offload=True)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_drafts_handler is not None:
        @router.get("/api/system/stream/drafts")
        async def stream_drafts(limit: int = 20):
            if not 1 <= limit <= 100:
                raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
            try:
                return await _call_handler(stream_drafts_handler, limit, offload=True)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    if stream_draft_generate_handler is not None:
        @router.post("/api/system/stream/drafts")
        async def stream_draft_generate(payload: dict[str, Any]):
            _strict_payload(payload, {"eventId", "workspaceId", "sessionId", "retry"})
            try:
                return await _call_handler(stream_draft_generate_handler, payload)
            except ValueError as exc:
                code = str(getattr(exc, "code", "") or "")
                status = 404 if code == "event_not_found" else 403 if code == "workspace_mismatch" else 503 if code in {"turn_service_unavailable", "llm_unavailable"} else 422
                raise HTTPException(status_code=status, detail=str(exc)) from exc

    if stream_draft_consume_handler is not None:
        @router.post("/api/system/stream/drafts/consume")
        async def stream_draft_consume(payload: dict[str, Any] | None = None):
            body = dict(payload or {})
            _strict_payload(body, {"limit", "workspaceId", "sessionId"})
            try:
                return await _call_handler(stream_draft_consume_handler, body)
            except ValueError as exc:
                code = str(getattr(exc, "code", "") or "")
                status = 403 if code == "workspace_mismatch" else 422
                raise HTTPException(status_code=status, detail=str(exc)) from exc

    if stream_draft_consumer_status_handler is not None:
        @router.get("/api/system/stream/draft-consumer")
        async def stream_draft_consumer_status():
            return await _call_handler(stream_draft_consumer_status_handler, offload=True)

    if stream_draft_consumer_toggle_handler is not None:
        @router.post("/api/system/stream/draft-consumer")
        async def stream_draft_consumer_toggle(payload: dict[str, Any]):
            _strict_payload(payload, {"enabled"})
            try:
                return await _call_handler(stream_draft_consumer_toggle_handler, payload)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
