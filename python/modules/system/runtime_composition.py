from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..agent.skill_store import SkillCatalogStore
from .active_workspace_state import ActiveWorkspaceState
from .runtime_endpoints import (
    build_active_workspace_endpoint,
    build_activity_frame_endpoints,
    build_add_mcp_endpoint,
    build_agent_plugin_state_endpoint,
    build_agent_trace_state_endpoint,
    build_cancel_schedule_endpoint,
    build_capabilities_state_endpoint,
    build_capability_snapshot,
    build_clear_permissions_endpoint,
    build_companion_opportunity_outcome_endpoint,
    build_connector_registry_endpoint,
    build_create_interval_schedule_endpoint,
    build_create_once_schedule_endpoint,
    build_disable_connector_endpoint,
    build_experience_metrics_endpoint,
    build_health_endpoint,
    build_heartbeat_goal_cancel_endpoint,
    build_heartbeat_opportunity_accept_endpoint,
    build_heartbeat_status_endpoint,
    build_imported_skills_state_endpoint,
    build_install_mcp_preset_endpoint,
    build_mcp_state_endpoint,
    build_memory_pipeline_query_endpoint,
    build_orchestration_snapshot,
    build_orchestration_state_endpoint,
    build_permissions_state_endpoint,
    build_platform_capability_endpoint,
    build_provider_registry_endpoint,
    build_readiness_endpoint,
    build_refresh_mcp_endpoint,
    build_remove_imported_skills_endpoint,
    build_remove_mcp_endpoint,
    build_remove_schedule_endpoint,
    build_revoke_permission_endpoint,
    build_run_schedule_now_endpoint,
    build_save_imported_skills_endpoint,
    build_schedules_state_endpoint,
    build_system_status_endpoint,
    build_toggle_agent_plugin_endpoint,
    build_toggle_mcp_endpoint,
    build_toggle_schedule_endpoint,
    build_update_agent_plugin_config_endpoint,
    build_voice_diagnostics_endpoint,
)


@dataclass(frozen=True)
class RuntimeHandlers:
    health: Callable[..., Any]
    readiness: Callable[..., Any]
    onboarding_readiness_state: Callable[..., Any]
    onboarding_readiness_run: Callable[..., Any]
    onboarding_readiness_retry: Callable[..., Any]
    onboarding_readiness_cancel: Callable[..., Any]
    onboarding_readiness_action: Callable[..., Any]
    system_status: Callable[..., Any]
    heartbeat_status: Callable[..., Any]
    companion_runtime_status: Callable[..., Any]
    companion_opportunity_outcome: Callable[..., Any]
    heartbeat_opportunity_accept: Callable[..., Any]
    heartbeat_goal_cancel: Callable[..., Any]
    proactive_settings_get: Callable[..., Any]
    proactive_settings_patch: Callable[..., Any]
    activity_frames_list: Callable[..., Any]
    activity_frames_rebuild: Callable[..., Any]
    activity_frame_delete: Callable[..., Any]
    proactive_feedback: Callable[..., Any]
    capabilities_state: Callable[..., Any]
    provider_registry: Callable[..., Any]
    connector_registry: Callable[..., Any]
    platform_matrix: Callable[..., Any]
    disable_connector: Callable[..., Any]
    orchestration_state: Callable[..., Any]
    active_workspace: Callable[..., Any]
    memory_pipeline_query: Callable[..., Any]
    permissions_state: Callable[..., Any]
    revoke_permission: Callable[..., Any]
    clear_permissions: Callable[..., Any]
    schedules_state: Callable[..., Any]
    create_once_schedule: Callable[..., Any]
    create_interval_schedule: Callable[..., Any]
    remove_schedule: Callable[..., Any]
    toggle_schedule: Callable[..., Any]
    run_schedule_now: Callable[..., Any]
    cancel_schedule: Callable[..., Any]
    agent_trace_state: Callable[..., Any]
    experience_metrics_state: Callable[..., Any]
    voice_diagnostics_state: Callable[..., Any]
    product_metrics_consent_state: Callable[..., Any]
    product_metrics_consent_patch: Callable[..., Any]
    mcp_state: Callable[..., Any]
    toggle_mcp: Callable[..., Any]
    add_mcp: Callable[..., Any]
    install_mcp_preset: Callable[..., Any]
    remove_mcp: Callable[..., Any]
    refresh_mcp: Callable[..., Any]
    agent_plugin_state: Callable[..., Any]
    toggle_agent_plugin: Callable[..., Any]
    update_agent_plugin_config: Callable[..., Any]
    imported_skills_state: Callable[..., Any]
    save_imported_skills: Callable[..., Any]
    remove_imported_skills: Callable[..., Any]


def product_metrics_consent_snapshot(product_metrics_consent_store: Any) -> dict[str, Any]:
    """Project durable consent without allowing corrupt state to enable collection."""
    try:
        consented = bool(product_metrics_consent_store.load())
    except (OSError, TypeError, ValueError):
        consented = False
    return {
        "consented": consented,
        "scope": "local_product_metrics",
        "transport": "not_configured",
    }


def build_runtime_handlers(
    *,
    service_manager: Any,
    health_checker: Any,
    config_snapshot_provider: Callable[[], dict[str, Any]],
    sio_server: Any,
    active_workspace_state: ActiveWorkspaceState,
    active_workspace_id_provider: Callable[[], str],
    db_repo_provider: Callable[[], Any],
    heartbeat_scheduler_provider: Callable[[], Any],
    companion_runtime_status: Callable[..., Any],
    retrieval_pipeline_provider: Callable[[], Any],
    relationship_summary_provider: Callable[[], Any],
    companion_runtime_provider: Callable[[int], dict[str, Any]],
    voice_diagnostics_provider: Callable[[], Any] | None = None,
    build_memory_query_request: Callable[..., Any],
    llm_health_provider: Callable[..., Any],
    tts_health_provider: Callable[..., Any],
    database_health_provider: Callable[..., Any],
    asr_health_provider: Callable[..., Any],
    ocr_health_provider: Callable[..., Any],
    memory_health_provider: Callable[..., Any],
    llm_client_provider: Callable[[], Any] | None,
    tts_client_provider: Callable[[], Any] | None,
    asr_manager_provider: Callable[[], Any] | None,
    vision_client_provider: Callable[[], Any] | None,
    generation_manager_provider: Callable[[], Any],
    svc_client_provider: Callable[[], Any],
    memory_status_provider: Callable[[], Any],
    onboarding_readiness: Any,
    product_metrics_consent_store: Any,
    message_connector_registry: Any | None = None,
) -> RuntimeHandlers:
    skill_store = SkillCatalogStore()
    activity_endpoints = build_activity_frame_endpoints(
        service_provider=lambda: sio_server.runtime.activity_frame_service if sio_server.runtime else None,
        active_workspace_id_provider=active_workspace_id_provider,
    )

    def product_metrics_consent_state() -> dict[str, Any]:
        return product_metrics_consent_snapshot(product_metrics_consent_store)

    def product_metrics_consent_patch(consented: bool) -> dict[str, Any]:
        product_metrics_consent_store.save(consented)
        return product_metrics_consent_state()

    return RuntimeHandlers(
        health=build_health_endpoint(health_handler=health_checker.check_all),
        readiness=build_readiness_endpoint(
            llm_health_provider=llm_health_provider,
            tts_health_provider=tts_health_provider,
            database_health_provider=database_health_provider,
            asr_health_provider=asr_health_provider,
            ocr_health_provider=ocr_health_provider,
            memory_health_provider=memory_health_provider,
            generation_manager_provider=generation_manager_provider,
            svc_client_provider=svc_client_provider,
            onboarding_readiness=onboarding_readiness,
        ),
        onboarding_readiness_state=onboarding_readiness.snapshot,
        onboarding_readiness_run=onboarding_readiness.start,
        onboarding_readiness_retry=onboarding_readiness.retry,
        onboarding_readiness_cancel=onboarding_readiness.cancel,
        onboarding_readiness_action=onboarding_readiness.execute_action,
        system_status=build_system_status_endpoint(
            service_manager=service_manager,
            health_checker=health_checker,
            config_snapshot_provider=config_snapshot_provider,
            memory_status_provider=memory_status_provider,
        ),
        heartbeat_status=build_heartbeat_status_endpoint(
            heartbeat_scheduler_provider=heartbeat_scheduler_provider,
            active_workspace_id_provider=active_workspace_id_provider,
            db_repo_provider=db_repo_provider,
        ),
        companion_runtime_status=companion_runtime_status,
        companion_opportunity_outcome=build_companion_opportunity_outcome_endpoint(
            heartbeat_scheduler_provider=heartbeat_scheduler_provider,
        ),
        heartbeat_opportunity_accept=build_heartbeat_opportunity_accept_endpoint(
            heartbeat_scheduler_provider=heartbeat_scheduler_provider,
            turn_service_provider=lambda: sio_server.runtime.turn_service if sio_server.runtime else None,
            authorization_callback=lambda acceptance, _pending: (
                sio_server.runtime is not None
                and sio_server.runtime.turn_service is not None
                and acceptance.workspace_id == active_workspace_id_provider()
            ),
        ),
        heartbeat_goal_cancel=build_heartbeat_goal_cancel_endpoint(heartbeat_scheduler_provider=heartbeat_scheduler_provider),
        proactive_settings_get=activity_endpoints["get_settings"],
        proactive_settings_patch=activity_endpoints["patch_settings"],
        activity_frames_list=activity_endpoints["list_frames"],
        activity_frames_rebuild=activity_endpoints["rebuild"],
        activity_frame_delete=activity_endpoints["delete_frame"],
        proactive_feedback=activity_endpoints["feedback"],
        capabilities_state=build_capabilities_state_endpoint(
            tool_registry_provider=lambda: sio_server.runtime.tool_registry if sio_server.runtime else None,
            capability_snapshot_builder=build_capability_snapshot,
        ),
        provider_registry=build_provider_registry_endpoint(
            config_snapshot_provider=config_snapshot_provider,
            health_providers={
                "llm": llm_health_provider,
                "tts": tts_health_provider,
                "asr": asr_health_provider,
            },
            client_providers={
                "llm": llm_client_provider or (lambda: None),
                "tts": tts_client_provider or (lambda: None),
                "asr": asr_manager_provider or (lambda: None),
                "vision": vision_client_provider or (lambda: None),
            },
        ),
        connector_registry=build_connector_registry_endpoint(
            mcp_manager=sio_server.mcp_manager,
            plugin_manager=sio_server.plugin_manager,
            adapter_registry=message_connector_registry,
        ),
        platform_matrix=build_platform_capability_endpoint(),
        disable_connector=build_disable_connector_endpoint(
            mcp_manager=sio_server.mcp_manager,
            plugin_manager=sio_server.plugin_manager,
            adapter_registry=message_connector_registry,
        ),
        orchestration_state=build_orchestration_state_endpoint(
            orchestration_snapshot_builder=build_orchestration_snapshot,
        ),
        active_workspace=build_active_workspace_endpoint(
            active_workspace_state=active_workspace_state,
            db_repo_provider=db_repo_provider,
        ),
        memory_pipeline_query=build_memory_pipeline_query_endpoint(
            retrieval_pipeline_provider=retrieval_pipeline_provider,
            active_workspace_id_provider=active_workspace_id_provider,
            db_repo_provider=db_repo_provider,
            relationship_summary_provider=relationship_summary_provider,
            companion_runtime_provider=companion_runtime_provider,
            build_memory_query_request=build_memory_query_request,
        ),
        permissions_state=build_permissions_state_endpoint(sio_server.policy_engine),
        revoke_permission=build_revoke_permission_endpoint(sio_server.policy_engine),
        clear_permissions=build_clear_permissions_endpoint(sio_server.policy_engine),
        schedules_state=build_schedules_state_endpoint(sio_server.schedule_store),
        create_once_schedule=build_create_once_schedule_endpoint(sio_server.scheduler),
        create_interval_schedule=build_create_interval_schedule_endpoint(sio_server.scheduler),
        remove_schedule=build_remove_schedule_endpoint(sio_server.scheduler),
        toggle_schedule=build_toggle_schedule_endpoint(sio_server.scheduler),
        run_schedule_now=build_run_schedule_now_endpoint(sio_server.scheduler),
        cancel_schedule=build_cancel_schedule_endpoint(sio_server.scheduler),
        agent_trace_state=build_agent_trace_state_endpoint(sio_server.trace_store),
        experience_metrics_state=build_experience_metrics_endpoint(sio_server.experience_metrics),
        voice_diagnostics_state=build_voice_diagnostics_endpoint(
            diagnostics_provider=voice_diagnostics_provider or (lambda: None),
            asr_client_provider=asr_manager_provider,
            tts_client_provider=tts_client_provider,
        ),
        product_metrics_consent_state=product_metrics_consent_state,
        product_metrics_consent_patch=product_metrics_consent_patch,
        mcp_state=build_mcp_state_endpoint(sio_server.mcp_manager),
        toggle_mcp=build_toggle_mcp_endpoint(sio_server.mcp_manager),
        add_mcp=build_add_mcp_endpoint(sio_server.mcp_manager),
        install_mcp_preset=build_install_mcp_preset_endpoint(sio_server.mcp_manager),
        remove_mcp=build_remove_mcp_endpoint(sio_server.mcp_manager),
        refresh_mcp=build_refresh_mcp_endpoint(sio_server.mcp_manager),
        agent_plugin_state=build_agent_plugin_state_endpoint(sio_server.plugin_manager),
        toggle_agent_plugin=build_toggle_agent_plugin_endpoint(sio_server.plugin_manager),
        update_agent_plugin_config=build_update_agent_plugin_config_endpoint(sio_server.plugin_manager),
        imported_skills_state=build_imported_skills_state_endpoint(skill_store),
        save_imported_skills=build_save_imported_skills_endpoint(skill_store),
        remove_imported_skills=build_remove_imported_skills_endpoint(skill_store),
    )


def build_system_router_from_handlers(
    *,
    create_system_router: Callable[..., Any],
    handlers: RuntimeHandlers,
) -> Any:
    return create_system_router(
        health_handler=handlers.health,
        readiness_handler=handlers.readiness,
        onboarding_readiness_state_handler=handlers.onboarding_readiness_state,
        onboarding_readiness_run_handler=handlers.onboarding_readiness_run,
        onboarding_readiness_retry_handler=handlers.onboarding_readiness_retry,
        onboarding_readiness_cancel_handler=handlers.onboarding_readiness_cancel,
        onboarding_readiness_action_handler=handlers.onboarding_readiness_action,
        system_status_handler=handlers.system_status,
        heartbeat_status_handler=handlers.heartbeat_status,
        companion_runtime_handler=handlers.companion_runtime_status,
        companion_opportunity_outcome_handler=handlers.companion_opportunity_outcome,
        heartbeat_opportunity_accept_handler=handlers.heartbeat_opportunity_accept,
        heartbeat_goal_cancel_handler=handlers.heartbeat_goal_cancel,
        proactive_settings_get_handler=handlers.proactive_settings_get,
        proactive_settings_patch_handler=handlers.proactive_settings_patch,
        activity_frames_list_handler=handlers.activity_frames_list,
        activity_frames_rebuild_handler=handlers.activity_frames_rebuild,
        activity_frame_delete_handler=handlers.activity_frame_delete,
        proactive_feedback_handler=handlers.proactive_feedback,
        capabilities_state_handler=handlers.capabilities_state,
        provider_registry_handler=handlers.provider_registry,
        connector_registry_handler=handlers.connector_registry,
        platform_matrix_handler=handlers.platform_matrix,
        disable_connector_handler=handlers.disable_connector,
        orchestration_state_handler=handlers.orchestration_state,
        active_workspace_handler=handlers.active_workspace,
        permissions_handler=handlers.permissions_state,
        revoke_permission_handler=handlers.revoke_permission,
        clear_permissions_handler=handlers.clear_permissions,
        schedules_handler=handlers.schedules_state,
        create_once_schedule_handler=handlers.create_once_schedule,
        create_interval_schedule_handler=handlers.create_interval_schedule,
        remove_schedule_handler=handlers.remove_schedule,
        toggle_schedule_handler=handlers.toggle_schedule,
        run_schedule_now_handler=handlers.run_schedule_now,
        cancel_schedule_handler=handlers.cancel_schedule,
        agent_trace_handler=handlers.agent_trace_state,
        experience_metrics_handler=handlers.experience_metrics_state,
        voice_diagnostics_handler=handlers.voice_diagnostics_state,
        product_metrics_consent_handler=handlers.product_metrics_consent_state,
        product_metrics_consent_patch_handler=handlers.product_metrics_consent_patch,
        mcp_state_handler=handlers.mcp_state,
        toggle_mcp_handler=handlers.toggle_mcp,
        add_mcp_handler=handlers.add_mcp,
        install_mcp_preset_handler=handlers.install_mcp_preset,
        remove_mcp_handler=handlers.remove_mcp,
        refresh_mcp_handler=handlers.refresh_mcp,
        agent_plugin_state_handler=handlers.agent_plugin_state,
        toggle_agent_plugin_handler=handlers.toggle_agent_plugin,
        update_agent_plugin_config_handler=handlers.update_agent_plugin_config,
        imported_skills_state_handler=handlers.imported_skills_state,
        save_imported_skills_handler=handlers.save_imported_skills,
        remove_imported_skills_handler=handlers.remove_imported_skills,
    )
