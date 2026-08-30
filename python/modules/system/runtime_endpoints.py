from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, cast

from fastapi.responses import JSONResponse

from ..agent.capability_registry import CapabilityRegistry
from ..agent.orchestration_registry import OrchestrationRegistry
from .connector_registry import build_connector_registry_snapshot
from .heartbeat import (
    HeartbeatOpportunityAcceptance,
    HeartbeatOpportunityAuthorizationError,
    HeartbeatOpportunityConflictError,
    HeartbeatOpportunityTurnBridge,
    HeartbeatOpportunityUnavailableError,
)
from .platform_capabilities import build_platform_capability_snapshot
from .provider_registry import build_provider_registry_snapshot

__all__ = [
    "build_active_workspace_endpoint",
    "build_activity_frame_endpoints",
    "build_add_mcp_endpoint",
    "build_agent_plugin_state_endpoint",
    "build_agent_trace_state_endpoint",
    "build_cancel_schedule_endpoint",
    "build_capabilities_state_endpoint",
    "build_capability_snapshot",
    "build_clear_permissions_endpoint",
    "build_companion_opportunity_outcome_endpoint",
    "build_companion_runtime_endpoint",
    "build_connector_registry_endpoint",
    "build_create_interval_schedule_endpoint",
    "build_create_once_schedule_endpoint",
    "build_disable_connector_endpoint",
    "build_experience_metrics_endpoint",
    "build_health_endpoint",
    "build_heartbeat_goal_cancel_endpoint",
    "build_heartbeat_opportunity_accept_endpoint",
    "build_heartbeat_status_endpoint",
    "build_imported_skills_state_endpoint",
    "build_install_mcp_preset_endpoint",
    "build_mcp_state_endpoint",
    "build_memory_pipeline_query_endpoint",
    "build_memory_query_request_payload",
    "build_orchestration_snapshot",
    "build_orchestration_state_endpoint",
    "build_permissions_state_endpoint",
    "build_platform_capability_endpoint",
    "build_provider_registry_endpoint",
    "build_readiness_endpoint",
    "build_refresh_mcp_endpoint",
    "build_remove_imported_skills_endpoint",
    "build_remove_mcp_endpoint",
    "build_remove_schedule_endpoint",
    "build_revoke_permission_endpoint",
    "build_run_schedule_now_endpoint",
    "build_save_imported_skills_endpoint",
    "build_schedules_state_endpoint",
    "build_system_status_endpoint",
    "build_toggle_agent_plugin_endpoint",
    "build_toggle_mcp_endpoint",
    "build_toggle_schedule_endpoint",
    "build_update_agent_plugin_config_endpoint",
    "build_voice_diagnostics_comfort_endpoint",
    "build_voice_diagnostics_comfort_signal_endpoint",
    "build_voice_diagnostics_begin_endpoint",
    "build_voice_diagnostics_endpoint",
    "build_voice_diagnostics_sample_endpoint",
]


def build_activity_frame_endpoints(
    *,
    service_provider: Callable[[], Any],
    active_workspace_id_provider: Callable[[], str],
) -> dict[str, Callable[..., Any]]:
    def _service() -> Any:
        service = service_provider()
        if service is None:
            raise RuntimeError("activity frame service is not initialized")
        return service

    def get_settings() -> dict[str, Any]:
        return _service().get_settings(active_workspace_id_provider())

    def patch_settings(payload: dict[str, Any]) -> dict[str, Any]:
        return _service().patch_settings(active_workspace_id_provider(), payload)

    def list_frames(limit: int = 50) -> dict[str, Any]:
        return _service().list_frames(active_workspace_id_provider(), limit)

    def rebuild(payload: dict[str, Any]) -> dict[str, Any]:
        extra = set(payload) - {"limit"}
        if extra:
            raise ValueError(f"unknown rebuild fields: {', '.join(sorted(extra))}")
        limit = payload.get("limit", 1000)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("limit must be an integer between 1 and 10000")
        return _service().rebuild(active_workspace_id_provider(), limit)

    def delete_frame(frame_id: str) -> dict[str, Any]:
        if not _service().delete_frame(active_workspace_id_provider(), frame_id):
            raise LookupError("activity frame was not found")
        return {"ok": True, "frameId": frame_id}

    def feedback(payload: dict[str, Any]) -> dict[str, Any]:
        return _service().feedback(active_workspace_id_provider(), payload)

    def feedback_summary() -> dict[str, Any]:
        return _service().feedback_summary(active_workspace_id_provider())

    return {
        "get_settings": get_settings,
        "patch_settings": patch_settings,
        "list_frames": list_frames,
        "rebuild": rebuild,
        "delete_frame": delete_frame,
        "feedback": feedback,
        "feedback_summary": feedback_summary,
    }


def build_companion_runtime_endpoint(*, snapshot_provider: Callable[[int], dict[str, Any]]) -> Callable[[int], dict[str, Any]]:
    def _endpoint(limit: int = 8) -> dict[str, Any]:
        return snapshot_provider(limit)

    return _endpoint


def build_companion_opportunity_outcome_endpoint(
    *, heartbeat_scheduler_provider: Callable[[], Any]
) -> Callable[[str, dict[str, Any]], JSONResponse | dict[str, Any]]:
    def _endpoint(job_id: str, payload: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        scheduler = heartbeat_scheduler_provider()
        if scheduler is None:
            return JSONResponse({"error": "heartbeat_scheduler_not_initialized"}, status_code=503)
        request_id = str(payload.get("request_id") or "").strip()
        outcome = str(payload.get("outcome") or "").strip().lower()
        reason = str(payload.get("reason") or "").strip() or None
        if not request_id or outcome not in {"delivered", "suppressed", "expired", "cancelled", "failed"}:
            return JSONResponse({"error": "invalid_opportunity_outcome"}, status_code=422)
        accepted = scheduler.resolve_opportunity(
            job_id=job_id,
            request_id=request_id,
            outcome=outcome,
            reason=reason,
        )
        if not accepted:
            return JSONResponse({"error": "opportunity_not_active"}, status_code=409)
        return {"ok": True, "job_id": job_id, "request_id": request_id, "outcome": outcome}

    return _endpoint


def build_heartbeat_opportunity_accept_endpoint(
    *,
    heartbeat_scheduler_provider: Callable[[], Any],
    turn_service_provider: Callable[[], Any],
    authorization_callback: Callable[..., Any] | None,
) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, JSONResponse | dict[str, Any]]]:
    bridge_state: dict[str, Any] = {}

    async def _endpoint(job_id: str, payload: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        scheduler = heartbeat_scheduler_provider()
        turn_service = turn_service_provider()
        if scheduler is None or turn_service is None:
            return JSONResponse(
                {"error": "heartbeat_turn_service_not_initialized"},
                status_code=503,
            )
        if authorization_callback is None:
            return JSONResponse(
                {"error": "heartbeat_acceptance_authorization_not_initialized"},
                status_code=503,
            )
        try:
            acceptance = HeartbeatOpportunityAcceptance.from_mapping(job_id, payload)
        except ValueError as exc:
            return JSONResponse({"error": "invalid_heartbeat_acceptance", "detail": str(exc)}, status_code=422)

        runtime_identity = (id(scheduler), id(turn_service), id(authorization_callback))
        if bridge_state.get("identity") != runtime_identity:
            bridge_state["identity"] = runtime_identity
            bridge_state["bridge"] = HeartbeatOpportunityTurnBridge(
                scheduler=scheduler,
                turn_service=turn_service,
                authorizer=authorization_callback,
            )
        bridge = bridge_state["bridge"]
        try:
            accepted = await bridge.accept(acceptance)
        except HeartbeatOpportunityAuthorizationError as exc:
            return JSONResponse({"error": "heartbeat_acceptance_denied", "detail": str(exc)}, status_code=403)
        except HeartbeatOpportunityConflictError as exc:
            return JSONResponse({"error": "heartbeat_opportunity_not_active", "detail": str(exc)}, status_code=409)
        except HeartbeatOpportunityUnavailableError as exc:
            return JSONResponse({"error": "heartbeat_acceptance_unavailable", "detail": str(exc)}, status_code=503)
        return accepted.response()

    return _endpoint


def build_heartbeat_goal_cancel_endpoint(*, heartbeat_scheduler_provider: Callable[[], Any]) -> Callable[[str, dict[str, Any]], JSONResponse | dict[str, Any]]:
    def _endpoint(goal_id: str, payload: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        scheduler = heartbeat_scheduler_provider()
        if scheduler is None:
            return JSONResponse({"error": "heartbeat_scheduler_not_initialized"}, status_code=503)
        reason = str(payload.get("reason") or "cancelled").strip() or "cancelled"
        if not scheduler.cancel_goal(goal_id, reason=reason):
            return JSONResponse({"error": "goal_not_cancellable", "goal_id": goal_id}, status_code=409)
        return {"ok": True, "goal_id": str(goal_id), "reason": reason}
    return _endpoint


def build_capability_snapshot(registry: Any) -> dict[str, Any]:
    return CapabilityRegistry(registry).snapshot()


def build_orchestration_snapshot() -> dict[str, Any]:
    return OrchestrationRegistry().snapshot()


def build_heartbeat_status_endpoint(
    *,
    heartbeat_scheduler_provider: Callable[[], Any],
    active_workspace_id_provider: Callable[[], str],
    db_repo_provider: Callable[[], Any],
) -> Callable[[], JSONResponse | dict[str, Any]]:
    def _endpoint() -> JSONResponse | dict[str, Any]:
        heartbeat_scheduler = heartbeat_scheduler_provider()
        if heartbeat_scheduler is None:
            return JSONResponse({"error": "heartbeat_scheduler_not_initialized"}, status_code=503)

        db_repo = db_repo_provider()
        active_workspace_id = active_workspace_id_provider()
        return {
            "running": heartbeat_scheduler.state.running,
            "interval_seconds": heartbeat_scheduler.state.interval_seconds,
            "tick_count": heartbeat_scheduler.state.tick_count,
            "last_tick_at": heartbeat_scheduler.state.last_tick_at,
            "persona": heartbeat_scheduler.state.persona,
            "events": heartbeat_scheduler.state.events,
            "behavior_events": heartbeat_scheduler.state.behavior_events,
            "goals": heartbeat_scheduler.goal_snapshot() if hasattr(heartbeat_scheduler, "goal_snapshot") else [],
            "active_workspace_id": active_workspace_id,
            "active_companion": db_repo.get_workspace_companion(active_workspace_id) if db_repo else None,
        }

    return _endpoint


def build_active_workspace_endpoint(
    *,
    active_workspace_state: Any,
    db_repo_provider: Callable[[], Any],
) -> Callable[[dict[str, Any]], JSONResponse | dict[str, Any]]:
    def _endpoint(payload: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        workspace_id = str(payload.get("workspace_id") or "default").strip() or "default"
        db_repo = db_repo_provider()
        if db_repo is not None and hasattr(db_repo, "list_workspaces"):
            workspaces = db_repo.list_workspaces()
            if not any(isinstance(item, dict) and item.get("id") == workspace_id for item in workspaces):
                return JSONResponse({"error": "workspace_not_found", "workspace_id": workspace_id}, status_code=404)
        active_workspace_id = active_workspace_state.set(workspace_id)
        return {
            "ok": True,
            "workspace_id": active_workspace_id,
            "companion": db_repo.get_workspace_companion(active_workspace_id) if db_repo else None,
        }

    return _endpoint


def build_capabilities_state_endpoint(
    *,
    tool_registry_provider: Callable[[], Any],
    capability_snapshot_builder: Callable[[Any], dict[str, Any]],
) -> Callable[[], dict[str, Any]]:
    def _endpoint() -> dict[str, Any]:
        registry = tool_registry_provider()
        if registry is None:
            return {
                "capabilities": [],
                "summary": {
                    "total": 0,
                    "builtin": 0,
                    "plugin": 0,
                    "mcp": 0,
                    "skill": 0,
                    "command": 0,
                    "approval_required": 0,
                },
            }

        return capability_snapshot_builder(registry)

    return _endpoint


def build_provider_registry_endpoint(
    *,
    config_snapshot_provider: Callable[[], dict[str, Any]],
    health_providers: dict[str, Callable[..., Any]],
    client_providers: dict[str, Callable[[], Any]],
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await build_provider_registry_snapshot(
            config_snapshot_provider=config_snapshot_provider,
            health_providers=health_providers,
            client_providers=client_providers,
        )

    return _endpoint


def build_voice_diagnostics_endpoint(
    *,
    diagnostics_provider: Callable[[], Any],
    asr_client_provider: Callable[[], Any] | None = None,
    tts_client_provider: Callable[[], Any] | None = None,
) -> Callable[[], dict[str, Any]]:
    """Expose transcript-free voice readiness and local latency evidence.

    The endpoint intentionally delegates to ``VoiceDiagnostics.runtime_snapshot``
    and never opens a microphone, emits audio, or probes a network provider.
    Device checks remain explicit user actions in the onboarding surface.
    """

    def _endpoint() -> dict[str, Any]:
        diagnostics = diagnostics_provider()
        if diagnostics is None:
            return {
                "sample_count": 0,
                "evidence_kinds": [],
                "evidence_claim": "synthetic_regression_only",
                "providers": {},
                "capability": {"voice": "degraded", "text_chat": "preserved", "text_chat_blocked_by_voice": False},
                "recommendations": ["voice diagnostics are not initialized"],
                "qualification": {
                    "status": "not_qualified",
                    "sample_count": 0,
                    "required_stages": [],
                    "recovery_quality": {"attempts": 0, "successes": 0, "success_rate": None},
                    "gaps": [{"kind": "diagnostics_unavailable"}],
                    "claim": "must_not_be_used_as_real_device_qualification",
                },
                "release_gate": {
                    "status": "not_qualified",
                    "qualification_status": "not_qualified",
                    "failures": [{"kind": "diagnostics_unavailable"}],
                    "claim": "must_not_be_used_as_voice_release_qualification",
                },
            }
        runtime_snapshot = getattr(diagnostics, "runtime_snapshot", None)
        if not callable(runtime_snapshot):
            raise TypeError("voice diagnostics runtime snapshot is unavailable")
        snapshot = runtime_snapshot(
            asr=asr_client_provider() if asr_client_provider is not None else None,
            tts=tts_client_provider() if tts_client_provider is not None else None,
        )
        if not isinstance(snapshot, Mapping):
            raise TypeError("voice diagnostics runtime snapshot must be an object")
        projected = cast(dict[str, Any], dict(snapshot))

        # Qualification reports can contain machine/device/provider provenance.
        # Keep only bounded gate metadata in the API/UI projection; the full
        # redacted artifact remains an explicit release-runner concern.
        qualification_fn = getattr(diagnostics, "qualification_snapshot", None)
        release_gate_fn = getattr(diagnostics, "release_gate", None)
        if callable(qualification_fn):
            try:
                raw_qualification = qualification_fn()
            except (TypeError, ValueError, RuntimeError, OSError):
                raw_qualification = None
            if isinstance(raw_qualification, Mapping):
                gaps: list[dict[str, Any]] = []
                raw_gaps = raw_qualification.get("gaps")
                if isinstance(raw_gaps, list):
                    for item in raw_gaps[:32]:
                        if not isinstance(item, Mapping):
                            continue
                        gap: dict[str, Any] = {}
                        for key in ("kind", "stage", "required", "actual", "fields"):
                            value = item.get(key)
                            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                                gap[key] = value
                            elif key == "fields" and isinstance(value, list):
                                gap[key] = [str(field)[:96] for field in value[:32]]
                        if gap:
                            gaps.append(gap)
                recovery = raw_qualification.get("recovery_quality")
                recovery_summary = {
                    "attempts": 0,
                    "successes": 0,
                    "success_rate": None,
                }
                if isinstance(recovery, Mapping):
                    attempts = recovery.get("attempts")
                    successes = recovery.get("successes")
                    success_rate = recovery.get("success_rate")
                    if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 0:
                        recovery_summary["attempts"] = attempts
                    if isinstance(successes, int) and not isinstance(successes, bool) and successes >= 0:
                        recovery_summary["successes"] = successes
                    if isinstance(success_rate, (int, float)) and not isinstance(success_rate, bool) and math.isfinite(float(success_rate)) and 0 <= float(success_rate) <= 1:
                        recovery_summary["success_rate"] = float(success_rate)
                projected["qualification"] = {
                    "status": raw_qualification.get("status") if raw_qualification.get("status") in {"qualified", "not_qualified"} else "not_qualified",
                    "sample_count": raw_qualification.get("sample_count") if isinstance(raw_qualification.get("sample_count"), int) and raw_qualification.get("sample_count") >= 0 else 0,
                    "required_stages": [str(stage)[:96] for stage in raw_qualification.get("required_stages", [])[:32]] if isinstance(raw_qualification.get("required_stages"), list) else [],
                    "recovery_quality": recovery_summary,
                    "gaps": gaps,
                    "claim": str(raw_qualification.get("claim") or "must_not_be_used_as_real_device_qualification")[:160],
                }
        if callable(release_gate_fn):
            try:
                raw_gate = release_gate_fn()
            except (TypeError, ValueError, RuntimeError, OSError):
                raw_gate = None
            if isinstance(raw_gate, Mapping):
                failures: list[dict[str, Any]] = []
                raw_failures = raw_gate.get("failures")
                if isinstance(raw_failures, list):
                    for item in raw_failures[:32]:
                        if not isinstance(item, Mapping):
                            continue
                        failure: dict[str, Any] = {}
                        for key in ("kind", "stage", "budget_ms", "p95_ms", "required", "actual"):
                            value = item.get(key)
                            if isinstance(value, (str, int, float)) and not isinstance(value, bool) and (not isinstance(value, float) or math.isfinite(value)):
                                failure[key] = value
                        if failure:
                            failures.append(failure)
                projected["release_gate"] = {
                    "status": raw_gate.get("status") if raw_gate.get("status") in {"pass", "fail"} else "fail",
                    "qualification_status": raw_gate.get("qualification_status") if raw_gate.get("qualification_status") in {"qualified", "not_qualified"} else "not_qualified",
                    "failures": failures,
                    "claim": str(raw_gate.get("claim") or "must_not_be_used_as_voice_release_qualification")[:160],
                }
        return projected

    return _endpoint


def build_voice_diagnostics_begin_endpoint(
    *,
    diagnostics_provider: Callable[[], Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Start an isolated renderer voice-diagnostics run.

    Runtime voice samples are intentionally scoped to one renderer session.  A
    new run clears the bounded in-memory/persisted measurements so a workspace
    switch or reconnect cannot make old comfort data look like current data.
    The caller receives only the safe run label; no transcript, audio, or
    credentials are accepted by this endpoint.
    """

    allowed = {"run_id"}
    safe_label = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,95}$")
    secret_pattern = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]|token\s*[=:]|secret\s*[=:])")

    def _endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("voice diagnostics run payload must be an object")
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        run_id = payload.get("run_id")
        if run_id is not None:
            if (
                not isinstance(run_id, str)
                or not run_id.strip()
                or len(run_id.strip()) > 96
                or secret_pattern.search(run_id)
                or not safe_label.fullmatch(run_id.strip())
            ):
                raise ValueError("run_id must be a non-empty safe label of 96 characters or less")
            run_id = run_id.strip()
        diagnostics = diagnostics_provider()
        if diagnostics is None:
            raise RuntimeError("voice diagnostics are not initialized")
        begin_run = getattr(diagnostics, "begin_run", None)
        snapshot = getattr(diagnostics, "snapshot", None)
        if not callable(begin_run) or not callable(snapshot):
            raise TypeError("voice diagnostics run lifecycle is unavailable")
        selected_run_id = begin_run(run_id=run_id)
        current = snapshot()
        if not isinstance(current, Mapping):
            raise TypeError("voice diagnostics snapshot must be an object")
        return {
            "ok": True,
            "run_id": selected_run_id,
            "sample_count": int(current.get("sample_count", 0)),
            "schemaVersion": "yuizaki.voice-diagnostics-run.v1",
        }

    return _endpoint


def build_voice_diagnostics_comfort_endpoint(
    *,
    diagnostics_provider: Callable[[], Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Record one transcript-free comfort fixture and return a safe snapshot."""

    allowed = {
        "scenario",
        "stop_audio_latency_ms",
        "interrupt_ack_latency_ms",
        "false_interruption",
        "first_audio_latency_ms",
        "continuous_turn_completed",
        "run_id",
    }
    latency_fields = {
        "stop_audio_latency_ms",
        "interrupt_ack_latency_ms",
        "first_audio_latency_ms",
    }
    secret_pattern = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]|token\s*[=:]|secret\s*[=:])")
    run_id_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,95}$")

    def _endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("voice comfort payload must be an object")
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

        scenario = payload.get("scenario")
        if not isinstance(scenario, str) or not scenario.strip() or len(scenario.strip()) > 64:
            raise ValueError("scenario must be a non-empty string of 64 characters or less")

        normalized: dict[str, Any] = {"scenario": scenario.strip()}
        for field_name in latency_fields:
            if field_name not in payload or payload[field_name] is None:
                normalized[field_name] = None
                continue
            value = payload[field_name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be a finite non-negative number")
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0 or numeric > 120_000:
                raise ValueError(f"{field_name} must be between 0 and 120000")
            normalized[field_name] = numeric

        for field_name in ("false_interruption", "continuous_turn_completed"):
            if field_name not in payload or payload[field_name] is None:
                normalized[field_name] = False if field_name == "false_interruption" else None
            elif not isinstance(payload[field_name], bool):
                raise TypeError(f"{field_name} must be a boolean")
            else:
                normalized[field_name] = payload[field_name]

        if "run_id" in payload and payload["run_id"] is not None:
            run_id = payload["run_id"]
            if (
                not isinstance(run_id, str)
                or not run_id.strip()
                or len(run_id.strip()) > 96
                or secret_pattern.search(run_id)
                or not run_id_pattern.fullmatch(run_id.strip())
            ):
                raise ValueError("run_id must be a non-empty safe label of 96 characters or less")
            normalized["run_id"] = run_id.strip()
        else:
            normalized["run_id"] = None

        diagnostics = diagnostics_provider()
        if diagnostics is None:
            raise RuntimeError("voice diagnostics are not initialized")
        record = getattr(diagnostics, "record_comfort_scenario", None)
        snapshot = getattr(diagnostics, "comfort_snapshot", None)
        if not callable(record) or not callable(snapshot):
            raise TypeError("voice comfort diagnostics are unavailable")
        record(**normalized)
        result = snapshot()
        if not isinstance(result, Mapping):
            raise TypeError("voice comfort snapshot must be an object")
        return dict(result)

    return _endpoint


def build_voice_diagnostics_comfort_signal_endpoint(
    *,
    diagnostics_provider: Callable[[], Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Record one explicit transcript/audio-free comfort signal."""

    allowed = {"signal", "source", "confidence", "duration_ms", "run_id"}
    signals = {"hesitation", "backchannel", "background_speech"}
    sources = {"provider_vad", "local_vad", "classifier"}
    safe_label = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,95}$")
    secret_pattern = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]|token\s*[=:]|secret\s*[=:])")

    def _number(payload: dict[str, Any], field_name: str, *, maximum: float) -> float | None:
        value = payload.get(field_name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be a finite non-negative number")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0 or numeric > maximum:
            raise ValueError(f"{field_name} must be between 0 and {maximum:g}")
        return numeric

    def _endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("voice comfort signal payload must be an object")
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        signal = payload.get("signal")
        source = payload.get("source")
        if not isinstance(signal, str) or signal.strip() not in signals:
            raise ValueError("signal is unsupported")
        if not isinstance(source, str) or source.strip() not in sources:
            raise ValueError("source is unsupported")
        confidence = _number(payload, "confidence", maximum=1.0)
        if confidence is None:
            raise ValueError("confidence is required")
        duration_ms = _number(payload, "duration_ms", maximum=120_000)
        run_id = payload.get("run_id")
        if run_id is not None:
            if (
                not isinstance(run_id, str)
                or not run_id.strip()
                or len(run_id.strip()) > 96
                or secret_pattern.search(run_id)
                or not safe_label.fullmatch(run_id.strip())
            ):
                raise ValueError("run_id must be a non-empty safe label of 96 characters or less")
            run_id = run_id.strip()
        normalized = {
            "signal": signal.strip(),
            "source": source.strip(),
            "confidence": confidence,
            "duration_ms": duration_ms,
            "run_id": run_id,
        }
        diagnostics = diagnostics_provider()
        if diagnostics is None:
            raise RuntimeError("voice diagnostics are not initialized")
        record = getattr(diagnostics, "record_comfort_signal", None)
        snapshot = getattr(diagnostics, "comfort_signal_snapshot", None)
        if not callable(record) or not callable(snapshot):
            raise TypeError("voice comfort signal diagnostics are unavailable")
        record(**normalized)
        result = snapshot()
        if not isinstance(result, Mapping):
            raise TypeError("voice comfort signal snapshot must be an object")
        return {
            **dict(result),
            "ok": True,
            "accepted": True,
            "signal": normalized["signal"],
            "source": normalized["source"],
        }

    return _endpoint


def build_voice_diagnostics_sample_endpoint(
    *,
    diagnostics_provider: Callable[[], Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Record one bounded, transcript-free realtime voice stage sample."""

    allowed = {
        "stage",
        "latency_ms",
        "ok",
        "provider",
        "error_kind",
        "recovered",
        "recovery_latency_ms",
        "playback_underruns",
        "run_id",
    }
    stages = {
        "capture",
        "asr",
        "asr_final",
        "llm",
        "first_token",
        "tts",
        "first_audio",
        "interruption",
        "playback",
        "playback_recovery",
        "round_trip",
    }
    safe_label = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,95}$")
    secret_pattern = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]|token\s*[=:]|secret\s*[=:])")

    def _number(payload: dict[str, Any], field_name: str, *, maximum: float = 120_000) -> float | None:
        value = payload.get(field_name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} must be a finite non-negative number")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0 or numeric > maximum:
            raise ValueError(f"{field_name} must be between 0 and {maximum:g}")
        return numeric

    def _label(payload: dict[str, Any], field_name: str) -> str | None:
        value = payload.get(field_name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a safe label")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 96 or secret_pattern.search(cleaned) or not safe_label.fullmatch(cleaned):
            raise ValueError(f"{field_name} must be a safe label of 96 characters or less")
        return cleaned

    def _endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("voice diagnostic sample payload must be an object")
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
        stage = payload.get("stage")
        if not isinstance(stage, str) or stage.strip() not in stages:
            raise ValueError("stage is unsupported")
        latency_ms = _number(payload, "latency_ms")
        if latency_ms is None:
            raise ValueError("latency_ms is required")
        ok = payload.get("ok", True)
        if not isinstance(ok, bool):
            raise TypeError("ok must be a boolean")
        recovered = payload.get("recovered")
        if recovered is not None and not isinstance(recovered, bool):
            raise TypeError("recovered must be a boolean")
        playback_underruns = payload.get("playback_underruns")
        if playback_underruns is not None and (
            isinstance(playback_underruns, bool)
            or not isinstance(playback_underruns, int)
            or not 0 <= playback_underruns <= 10_000
        ):
            raise ValueError("playback_underruns must be an integer between 0 and 10000")
        run_id = _label(payload, "run_id")
        normalized = {
            "stage": stage.strip(),
            "latency_ms": latency_ms,
            "ok": ok,
            "provider": _label(payload, "provider"),
            "error_kind": _label(payload, "error_kind"),
            "recovered": recovered,
            "recovery_latency_ms": _number(payload, "recovery_latency_ms"),
            "playback_underruns": playback_underruns,
            "run_id": run_id,
        }
        diagnostics = diagnostics_provider()
        if diagnostics is None:
            raise RuntimeError("voice diagnostics are not initialized")
        record = getattr(diagnostics, "record", None)
        if not callable(record):
            raise TypeError("voice diagnostics recorder is unavailable")
        record(**normalized)
        return {"ok": True, "accepted": True, "stage": normalized["stage"]}

    return _endpoint


def build_connector_registry_endpoint(
    *,
    mcp_manager: Any,
    plugin_manager: Any,
    adapter_registry: Any | None = None,
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        mcp_snapshot = await asyncio.to_thread(mcp_manager.snapshot)
        plugin_snapshot = await asyncio.to_thread(plugin_manager.snapshot)
        return build_connector_registry_snapshot(
            mcp_snapshot=mcp_snapshot,
            plugin_snapshot=plugin_snapshot,
            adapter_registry=adapter_registry,
        )

    return _endpoint


def build_platform_capability_endpoint() -> Callable[[], dict[str, Any]]:
    """Build a side-effect-free platform matrix endpoint."""

    def _endpoint() -> dict[str, Any]:
        return build_platform_capability_snapshot()

    return _endpoint


def build_disable_connector_endpoint(
    *,
    mcp_manager: Any,
    plugin_manager: Any,
    adapter_registry: Any | None = None,
) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(connector_id: str) -> dict[str, Any]:
        prefix, _, name = connector_id.partition(":")
        if adapter_registry is not None and connector_id in {"telegram", "discord", "qq", "wechat"}:
            connector = await asyncio.to_thread(adapter_registry.disable, connector_id)
            if connector is None:
                return {"ok": False, "connector": None, "error": "connector is not installed or cannot be disabled"}
            return {"ok": connector.get("state") == "disabled", "connector": connector}
        if not name or prefix not in {"mcp", "plugin"}:
            return {"ok": False, "connector": None, "error": "connector is not installed or cannot be disabled"}
        if prefix == "mcp":
            result = await asyncio.to_thread(mcp_manager.set_enabled, name, False)
            if result is None:
                return {"ok": False, "connector": None, "error": "connector not found"}
            await mcp_manager.refresh_one(name, timeout_seconds=3.0)
        else:
            result = await asyncio.to_thread(plugin_manager.set_enabled, name, False)
            if result is None:
                return {"ok": False, "connector": None, "error": "connector not found"}
        snapshot = await asyncio.to_thread(mcp_manager.snapshot)
        plugin_snapshot = await asyncio.to_thread(plugin_manager.snapshot)
        registry = build_connector_registry_snapshot(
            mcp_snapshot=snapshot,
            plugin_snapshot=plugin_snapshot,
            adapter_registry=adapter_registry,
        )
        connector = next((item for item in registry["connectors"] if item["id"] == connector_id), None)
        return {"ok": connector is not None and connector["state"] == "disabled", "connector": connector}

    return _endpoint


def build_orchestration_state_endpoint(
    *,
    orchestration_snapshot_builder: Callable[[], dict[str, Any]],
) -> Callable[[], dict[str, Any]]:
    def _endpoint() -> dict[str, Any]:
        return orchestration_snapshot_builder()

    return _endpoint


def build_memory_pipeline_query_endpoint(
    *,
    retrieval_pipeline_provider: Callable[[], Any],
    active_workspace_id_provider: Callable[[], str],
    db_repo_provider: Callable[[], Any],
    relationship_summary_provider: Callable[[], dict[str, Any]],
    companion_runtime_provider: Callable[[int], dict[str, Any]],
    build_memory_query_request: Callable[..., Any],
) -> Callable[[str, str | None, str | None, str | None, str | None, int], JSONResponse | Any]:
    def _endpoint(
        query: str,
        session_id: str | None = None,
        workspace_id: str | None = None,
        scope: str | None = None,
        layers: str | None = None,
        top_k: int = 5,
    ) -> JSONResponse | Any:
        retrieval_pipeline = retrieval_pipeline_provider()
        if retrieval_pipeline is None:
            return JSONResponse({"error": "retrieval_pipeline_not_initialized"}, status_code=503)

        request = build_memory_query_request_payload(
            query=query,
            session_id=session_id,
            workspace_id=workspace_id,
            scope=scope,
            layers=layers,
            top_k=top_k,
            active_workspace_id_provider=active_workspace_id_provider,
            db_repo_provider=db_repo_provider,
            relationship_summary_provider=relationship_summary_provider,
            companion_runtime_provider=companion_runtime_provider,
            build_memory_query_request=build_memory_query_request,
        )
        return retrieval_pipeline.recall(request)

    return _endpoint


def build_health_endpoint(*, health_handler: Callable[[], Coroutine[Any, Any, Any]]) -> Callable[[], Coroutine[Any, Any, Any]]:
    async def _endpoint() -> Any:
        return await health_handler()

    return _endpoint


def build_readiness_endpoint(
    *,
    llm_health_provider: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    tts_health_provider: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    database_health_provider: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    asr_health_provider: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    ocr_health_provider: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    memory_health_provider: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
    generation_manager_provider: Callable[[], Any],
    svc_client_provider: Callable[[], Any],
    onboarding_readiness: Any | None = None,
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        onboarding_snapshot: dict[str, Any] | None = None
        if onboarding_readiness is not None:
            onboarding_snapshot = await onboarding_readiness.run(
                ["backend.service", "llm.provider", "llm.model_chat"]
            )
        llm_ok, llm_msg = await llm_health_provider()
        tts_ok, tts_msg = await tts_health_provider()
        db_ok, db_msg = await database_health_provider()
        asr_ok, asr_msg = await asr_health_provider()
        ocr_ok, ocr_msg = await ocr_health_provider()
        memory_ok, memory_msg = await memory_health_provider()

        generation_ok = generation_manager_provider() is not None
        generation_msg = "Generation manager healthy" if generation_ok else "Generation manager not initialized"

        svc_client = svc_client_provider()
        svc_ok = svc_client is not None and bool(getattr(svc_client, "is_available", False))
        svc_msg = "SVC service healthy" if svc_ok else "SVC not available (optional)"

        checks: dict[str, dict[str, Any]] = {
            "backend_service": {"ok": True, "message": "Backend service is responding", "required": True},
            "generation_manager": {"ok": generation_ok, "message": generation_msg, "required": False},
            "llm": {"ok": bool(llm_ok), "message": llm_msg, "required": True},
            "tts": {"ok": bool(tts_ok), "message": tts_msg, "required": False},
            "database": {"ok": bool(db_ok), "message": db_msg, "required": False},
            "asr": {"ok": bool(asr_ok), "message": asr_msg, "required": False},
            "ocr": {"ok": bool(ocr_ok), "message": ocr_msg, "required": False},
            "memory": {"ok": bool(memory_ok), "message": memory_msg, "required": False},
            "svc": {"ok": bool(svc_ok), "message": svc_msg, "required": False},
        }

        if onboarding_snapshot is not None:
            probe_by_id = {item["id"]: item for item in onboarding_snapshot["probes"]}
            provider = probe_by_id["llm.provider"]
            model_chat = probe_by_id["llm.model_chat"]
            checks["llm_provider"] = {
                "ok": provider["status"] == "ready",
                "message": provider["message"],
                "required": True,
            }
            checks["llm_model_chat"] = {
                "ok": model_chat["status"] == "ready",
                "message": model_chat["message"],
                "required": True,
            }
            checks["llm"] = {
                "ok": checks["llm_provider"]["ok"] and checks["llm_model_chat"]["ok"],
                "message": model_chat["message"],
                "required": False,
            }

        return {
            "ready": all(item["ok"] for item in checks.values() if item["required"]),
            "readyForText": all(item["ok"] for item in checks.values() if item["required"]),
            "checks": checks,
        }

    return _endpoint


def build_memory_query_request_payload(
    *,
    query: str,
    session_id: str | None,
    workspace_id: str | None,
    scope: str | None,
    layers: str | None,
    top_k: int,
    active_workspace_id_provider: Callable[[], str],
    db_repo_provider: Callable[[], Any],
    relationship_summary_provider: Callable[[], dict[str, Any]],
    companion_runtime_provider: Callable[[int], dict[str, Any]],
    build_memory_query_request: Callable[..., Any],
) -> Any:
    db_repo = db_repo_provider()
    relationship_summary = relationship_summary_provider() or {}
    companion = db_repo.get_workspace_companion(active_workspace_id_provider()) if db_repo else {}
    runtime_snapshot = companion_runtime_provider(6)
    recent_signal_kinds = [
        str(item.get("kind") or "")
        for item in (runtime_snapshot.get("memory_state", {}).get("recent_signals", []) or [])
        if isinstance(item, dict)
    ]
    return build_memory_query_request(
        query=query,
        session_id=session_id,
        workspace_id=workspace_id,
        scope=scope,
        layers=layers,
        top_k=top_k,
        support_style=(companion or {}).get("support_style") if isinstance(companion, dict) else None,
        relationship_stage=relationship_summary.get("relationship_stage"),
        milestone_salience=relationship_summary.get("milestone_salience"),
        recent_signal_kinds=recent_signal_kinds,
    )


def build_permissions_state_endpoint(policy_engine: Any) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(
            lambda: {
                "remembered": policy_engine.get_remembered_decisions(),
                "audit": policy_engine.get_audit_log(200),
            }
        )

    return _endpoint


def build_revoke_permission_endpoint(policy_engine: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(tool_name: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            lambda: {
                "ok": policy_engine.revoke(tool_name, "socket"),
                "remembered": policy_engine.get_remembered_decisions(),
                "audit": policy_engine.get_audit_log(200),
            }
        )

    return _endpoint


def build_clear_permissions_endpoint(policy_engine: Any) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(
            lambda: {
                "ok": True,
                "cleared": policy_engine.clear(),
                "remembered": policy_engine.get_remembered_decisions(),
                "audit": policy_engine.get_audit_log(200),
            }
        )

    return _endpoint


def build_schedules_state_endpoint(schedule_store: Any) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(
            lambda: {
                "tasks": [task.__dict__ for task in schedule_store.list()],
            }
        )

    return _endpoint


def build_agent_trace_state_endpoint(trace_store: Any) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(trace_store.snapshot, 200)

    return _endpoint


def build_experience_metrics_endpoint(metrics_store: Any) -> Callable[[], dict[str, Any]]:
    def _endpoint() -> dict[str, Any]:
        return metrics_store.snapshot()

    return _endpoint


def build_mcp_state_endpoint(mcp_manager: Any) -> Callable[[], Coroutine[Any, Any, Any]]:
    async def _endpoint() -> Any:
        return await asyncio.to_thread(mcp_manager.snapshot)

    return _endpoint


def build_toggle_mcp_endpoint(mcp_manager: Any) -> Callable[[str, bool], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(server_name: str, enabled: bool) -> dict[str, Any]:
        result = await asyncio.to_thread(mcp_manager.set_enabled, server_name, enabled)
        await mcp_manager.refresh_one(server_name, timeout_seconds=3.0)
        return {"ok": result is not None, "server": result}

    return _endpoint


def build_add_mcp_endpoint(mcp_manager: Any) -> Callable[[str, str, str, bool, str | None, list[str] | None, dict[str, str] | None, dict[str, str] | None], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(
        name: str,
        base_url: str,
        transport: str,
        enabled: bool,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        server = await asyncio.to_thread(mcp_manager.add_server, name, base_url, transport, enabled, command, args, env, headers)
        await mcp_manager.refresh_one(name, timeout_seconds=3.0)
        return {"ok": True, "server": server}

    return _endpoint


def build_install_mcp_preset_endpoint(mcp_manager: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(preset_id: str) -> dict[str, Any]:
        server = await asyncio.to_thread(mcp_manager.install_preset, preset_id)
        if server is None:
            return {"ok": False, "server": None, "error": "unknown_mcp_preset"}
        await mcp_manager.refresh_one(str(server.get("name") or preset_id), timeout_seconds=3.0)
        return {"ok": True, "server": server}

    return _endpoint


def build_remove_mcp_endpoint(mcp_manager: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(server_name: str) -> dict[str, Any]:
        ok = await asyncio.to_thread(mcp_manager.remove_server, server_name)
        return {"ok": ok}

    return _endpoint


def build_refresh_mcp_endpoint(mcp_manager: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(server_name: str) -> dict[str, Any]:
        status = await mcp_manager.refresh_one(server_name, timeout_seconds=3.0)
        return {"ok": status is not None, "status": status}

    return _endpoint


def build_agent_plugin_state_endpoint(plugin_manager: Any) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(plugin_manager.snapshot)

    return _endpoint


def build_toggle_agent_plugin_endpoint(plugin_manager: Any) -> Callable[[str, bool], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(plugin_id: str, enabled: bool) -> dict[str, Any]:
        state = await asyncio.to_thread(plugin_manager.set_enabled, plugin_id, enabled)
        return {"ok": state is not None, "plugin": state}

    return _endpoint


def build_update_agent_plugin_config_endpoint(plugin_manager: Any) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(plugin_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = await plugin_manager.update_config(plugin_id, payload)
        return {"ok": state is not None, "plugin": state}

    return _endpoint


def build_imported_skills_state_endpoint(skill_store: Any) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(skill_store.snapshot)

    return _endpoint


def build_save_imported_skills_endpoint(skill_store: Any) -> Callable[[list[dict[str, Any]]], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(items: list[dict[str, Any]]) -> dict[str, Any]:
        return await asyncio.to_thread(skill_store.replace, items)

    return _endpoint


def build_remove_imported_skills_endpoint(skill_store: Any) -> Callable[[list[str]], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(skill_ids: list[str]) -> dict[str, Any]:
        return await asyncio.to_thread(skill_store.remove_many, skill_ids)

    return _endpoint


def build_system_status_endpoint(
    *,
    service_manager: Any,
    health_checker: Any,
    config_snapshot_provider: Callable[[], dict[str, Any]],
    memory_status_provider: Callable[[], Any],
) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint() -> dict[str, Any]:
        return await asyncio.to_thread(
            lambda: {
                "services": service_manager.get_status(),
                "health": health_checker.get_status(),
                "config": config_snapshot_provider(),
                "memory": (
                    memory_status.__dict__
                    if (memory_status := memory_status_provider())
                    else None
                ),
            }
        )

    return _endpoint


def build_create_once_schedule_endpoint(scheduler: Any) -> Callable[[str, str, int], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(name: str, prompt: str, run_after_seconds: int) -> dict[str, Any]:
        task = await scheduler.add_once(name, prompt, run_after_seconds)
        return {"ok": True, "task": task.__dict__}

    return _endpoint


def build_create_interval_schedule_endpoint(scheduler: Any) -> Callable[[str, str, int], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(name: str, prompt: str, interval_seconds: int) -> dict[str, Any]:
        task = await scheduler.add_interval(name, prompt, interval_seconds)
        return {"ok": True, "task": task.__dict__}

    return _endpoint


def build_remove_schedule_endpoint(scheduler: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(task_id: str) -> dict[str, Any]:
        await scheduler.remove_task(task_id)
        return {"ok": True}

    return _endpoint


def build_toggle_schedule_endpoint(scheduler: Any) -> Callable[[str, bool], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(task_id: str, enabled: bool) -> dict[str, Any]:
        task = await scheduler.set_enabled(task_id, enabled)
        return {"ok": task is not None, "task": task.__dict__ if task else None}

    return _endpoint


def build_run_schedule_now_endpoint(scheduler: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(task_id: str) -> dict[str, Any]:
        task = await scheduler.run_now(task_id)
        get_run = getattr(scheduler, "get_run", None)
        run = get_run(task_id) if task is not None and callable(get_run) else None
        return {"ok": task is not None, "task": task.__dict__ if task else None, "run": run}

    return _endpoint


def build_cancel_schedule_endpoint(scheduler: Any) -> Callable[[str], Coroutine[Any, Any, dict[str, Any]]]:
    async def _endpoint(task_or_job_id: str) -> dict[str, Any]:
        cancelled = await scheduler.cancel(task_or_job_id)
        get_run = getattr(scheduler, "get_run", None)
        run = get_run(task_or_job_id) if callable(get_run) else None
        return {"ok": cancelled, "run": run}

    return _endpoint
