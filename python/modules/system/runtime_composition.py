from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .active_workspace_state import ActiveWorkspaceState
from .runtime_endpoints import (
    build_active_workspace_endpoint,
    build_add_mcp_endpoint,
    build_agent_plugin_state_endpoint,
    build_agent_trace_state_endpoint,
    build_experience_metrics_endpoint,
    build_capabilities_state_endpoint,
    build_capability_snapshot,
    build_clear_permissions_endpoint,
    build_create_interval_schedule_endpoint,
    build_create_once_schedule_endpoint,
    build_health_endpoint,
    build_heartbeat_status_endpoint,
    build_install_mcp_preset_endpoint,
    build_imported_skills_state_endpoint,
    build_mcp_state_endpoint,
    build_memory_pipeline_query_endpoint,
    build_orchestration_snapshot,
    build_orchestration_state_endpoint,
    build_permissions_state_endpoint,
    build_readiness_endpoint,
    build_refresh_mcp_endpoint,
    build_remove_mcp_endpoint,
    build_remove_imported_skills_endpoint,
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
)
from ..agent.skill_store import SkillCatalogStore


@dataclass(frozen=True)
class RuntimeHandlers:
    health: Callable[..., Any]
    readiness: Callable[..., Any]
    system_status: Callable[..., Any]
    heartbeat_status: Callable[..., Any]
    companion_runtime_status: Callable[..., Any]
    capabilities_state: Callable[..., Any]
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
    agent_trace_state: Callable[..., Any]
    experience_metrics_state: Callable[..., Any]
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
    build_memory_query_request: Callable[..., Any],
    llm_health_provider: Callable[..., Any],
    tts_health_provider: Callable[..., Any],
    database_health_provider: Callable[..., Any],
    asr_health_provider: Callable[..., Any],
    ocr_health_provider: Callable[..., Any],
    memory_health_provider: Callable[..., Any],
    generation_manager_provider: Callable[[], Any],
    svc_client_provider: Callable[[], Any],
    memory_status_provider: Callable[[], Any],
) -> RuntimeHandlers:
    runtime = sio_server.runtime
    skill_store = SkillCatalogStore()
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
        ),
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
        capabilities_state=build_capabilities_state_endpoint(
            tool_registry_provider=lambda: runtime.tool_registry if runtime else None,
            capability_snapshot_builder=build_capability_snapshot,
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
        agent_trace_state=build_agent_trace_state_endpoint(sio_server.trace_store),
        experience_metrics_state=build_experience_metrics_endpoint(sio_server.experience_metrics),
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
    admin_token_provider: Callable[[], str],
) -> Any:
    return create_system_router(
        health_handler=handlers.health,
        readiness_handler=handlers.readiness,
        system_status_handler=handlers.system_status,
        heartbeat_status_handler=handlers.heartbeat_status,
        companion_runtime_handler=handlers.companion_runtime_status,
        capabilities_state_handler=handlers.capabilities_state,
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
        agent_trace_handler=handlers.agent_trace_state,
        experience_metrics_handler=handlers.experience_metrics_state,
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
        get_admin_token=admin_token_provider,
    )
