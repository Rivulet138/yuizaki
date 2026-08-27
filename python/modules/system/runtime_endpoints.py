from __future__ import annotations

import asyncio
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
    "build_voice_diagnostics_endpoint",
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

    return {
        "get_settings": get_settings,
        "patch_settings": patch_settings,
        "list_frames": list_frames,
        "rebuild": rebuild,
        "delete_frame": delete_frame,
        "feedback": feedback,
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
        return cast(dict[str, Any], dict(snapshot))

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
