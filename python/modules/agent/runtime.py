from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..agent_plugins.manager import PluginManager
from ..core.paths import data_dir_from_env
from ..system.memory_write_pipeline import build_task_completed_event, build_user_signal_event
from .activity_frames import ActivityFrameService, ActivityFrameStore
from .agent_trace_store import AgentTraceStore
from .companion_events import CompanionJobEventLog
from .computer_use import (
    ComputerUseAdapter,
    ComputerUseController,
    register_computer_use_tools,
)
from .default_tools import register_default_tools
from .desktop_actions import (
    DesktopActionAdapter,
    DesktopActionController,
    DesktopActionScope,
    register_desktop_action_tools,
)
from .mcp_manager import MCPManager
from .perception import PerceptionProviderRegistry
from .pipeline import AgentPipeline
from .policy_engine import PolicyEngine
from .runtime_context import RuntimeContext, RuntimeContextRegistry
from .schedule_store import ScheduleStore
from .scheduler import AgentScheduler
from .step_executor import StepExecutor
from .tool_executor import ToolExecutor
from .tool_registry import ToolRegistry
from .turn_outbox import TurnOutboxDispatcher, TurnOutboxWorker, TurnProjection
from .turn_service import TurnService
from .turn_store import TurnCommitStore


_FAILURE_PROJECTION_FIELDS = frozenset({
    "step_id", "failed_step_id", "kind", "category", "message",
    "retryable", "completed_steps",
})
_RECOVERY_PROJECTION_FIELDS = frozenset({
    "available", "action", "failed_step_id", "retryable", "scope",
    "single_use", "ttl_seconds", "handle",
})
_JOB_TERMINAL_PROJECTION_FIELDS = frozenset({
    "status", "job_id", "run_id", "conversation_id", "operation_id",
    "task_id", "task_name", "task_mode", "owner_agent_id",
    "owner_agent_role", "route_reason",
})


def _bounded_terminal_descriptor(
    value: Any,
    *,
    fields: frozenset[str],
) -> dict[str, Any] | None:
    """Copy only renderer-safe, bounded terminal metadata across the outbox.

    TurnCommitStore is the authority, but old or manually-authored commits may
    contain richer dictionaries.  Projection must remain fail-closed: payload,
    nested metadata, and raw resume tokens are never forwarded to the job log.
    """
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in fields:
        candidate = value.get(key)
        if key in {"available", "retryable", "single_use"}:
            if isinstance(candidate, bool):
                result[key] = candidate
        elif key == "ttl_seconds":
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                result[key] = max(0, min(candidate, 86_400))
        elif key == "completed_steps":
            if isinstance(candidate, (list, tuple)):
                result[key] = [
                    str(item).strip()[:120]
                    for item in candidate[:20]
                    if str(item).strip()
                ]
        elif isinstance(candidate, str):
            result[key] = candidate.strip()[:240]
    return result or None


@dataclass
class AgentRuntime:
    tool_registry: ToolRegistry
    mcp_manager: MCPManager
    policy_engine: PolicyEngine
    tool_executor: ToolExecutor
    step_executor: StepExecutor
    agent_pipeline: AgentPipeline
    trace_store: AgentTraceStore
    plugin_manager: PluginManager
    schedule_store: ScheduleStore
    scheduler: AgentScheduler
    # Optional for compatibility with callers constructing AgentRuntime
    # directly; create_agent_runtime always wires the shared pipeline facade.
    turn_service: TurnService | None = None
    desktop_adapter: DesktopActionAdapter | None = None
    desktop_action_controller: DesktopActionController | None = None
    computer_use_controller: ComputerUseController | None = None
    runtime_context_registry: RuntimeContextRegistry | None = None
    perception_registry: PerceptionProviderRegistry | None = None
    # Durable semantic-turn authority and projection outbox.  Keeping this on
    # the runtime makes the persistence boundary explicit and injectable.
    turn_store: TurnCommitStore | None = None
    turn_outbox_dispatcher: TurnOutboxDispatcher | None = None
    turn_outbox_worker: TurnOutboxWorker | None = None
    activity_frame_service: ActivityFrameService | None = None


def create_agent_runtime(
    *,
    schedule_context_factory: Callable[[Any], Any],
    schedule_workspace_id_provider: Callable[[], str] | None = None,
    schedule_interruption_epoch_provider: Callable[[], int] | None = None,
    trace_store: AgentTraceStore | None = None,
    policy_engine: PolicyEngine | None = None,
    tool_outcome_observer: Callable[[bool], None] | None = None,
    job_event_log: CompanionJobEventLog | None = None,
    desktop_adapter: DesktopActionAdapter | None = None,
    computer_use_adapter: ComputerUseAdapter | None = None,
    runtime_context_registry: RuntimeContextRegistry | None = None,
    perception_registry: PerceptionProviderRegistry | None = None,
    turn_store: TurnCommitStore | None = None,
) -> AgentRuntime:
    tool_registry = ToolRegistry()
    register_default_tools(tool_registry)
    desktop_action_controller = DesktopActionController(adapter=desktop_adapter)
    resolved_desktop_adapter = register_desktop_action_tools(
        tool_registry,
        controller=desktop_action_controller,
    )
    computer_use_controller = register_computer_use_tools(tool_registry, adapter=computer_use_adapter)

    mcp_manager = MCPManager()
    mcp_manager.register_tools(tool_registry)

    resolved_policy_engine = policy_engine or PolicyEngine()
    resolved_trace_store = trace_store or AgentTraceStore()
    resolved_job_event_log = job_event_log or CompanionJobEventLog()
    tool_executor = ToolExecutor(tool_registry, resolved_policy_engine, tool_outcome_observer)
    step_executor = StepExecutor()
    agent_pipeline = AgentPipeline()
    plugin_manager = PluginManager()
    schedule_store = ScheduleStore()
    scheduler = AgentScheduler(
        store=schedule_store,
        pipeline=agent_pipeline,
        context_factory=schedule_context_factory,
        workspace_id_provider=schedule_workspace_id_provider,
        interruption_epoch_provider=schedule_interruption_epoch_provider,
        job_event_log=resolved_job_event_log,
    )
    resolved_runtime_context_registry = runtime_context_registry or RuntimeContextRegistry()
    resolved_turn_store = turn_store or TurnCommitStore(data_dir_from_env() / "turn_commits.sqlite3")
    activity_frame_service = ActivityFrameService(
        ActivityFrameStore(data_dir_from_env() / "activity_frames.sqlite3"),
        resolved_turn_store,
    )

    def _projection_runtime_context(workspace_id: str | None) -> RuntimeContext | None:
        if not workspace_id:
            return None
        registered = resolved_runtime_context_registry.get(workspace_id)
        if registered is not None:
            return registered
        for candidate in resolved_runtime_context_registry.snapshot().values():
            if candidate.extras.get("shared_workspace_projection_repository") is True:
                return candidate
        return None

    def _projection_trigger(payload: dict[str, Any]) -> str:
        trigger = str(payload.get("trigger") or payload.get("source") or "").strip().lower()
        if trigger in {"schedule", "scheduled", "scheduler"}:
            return "scheduler"
        return trigger or "agent"

    async def _project_relationship_user_signal(event: dict[str, Any], context: Any | None) -> None:
        payload = event.get("payload")
        trigger = _projection_trigger(payload) if isinstance(payload, dict) else ""
        if (
            not isinstance(payload, dict)
            or (payload.get("autonomy_mode") == "silent" and trigger != "scheduler")
            or trigger not in {"http", "socket", "voice", "scheduler"}
        ):
            return
        workspace_id = str(payload.get("workspace_id") or "").strip() or None
        if trigger == "scheduler":
            if not payload.get("task_id") and not payload.get("job_id"):
                return
            if str(payload.get("outcome") or "completed") != "completed":
                return
            relationship_event = build_task_completed_event(
                task_name=str(payload.get("task_name") or "scheduled task"),
                task_id=str(payload.get("task_id") or payload.get("job_id") or "scheduled-task"),
                task_mode=str(payload.get("task_mode") or "once"),
                owner_agent_id=str(payload.get("owner_agent_id") or "scheduler"),
                owner_agent_role=str(payload.get("owner_agent_role") or "scheduler"),
                session_id=str(payload.get("session_id") or "") or None,
            )
        else:
            messages = payload.get("messages")
            if not isinstance(messages, list):
                raise TypeError("turn outbox relationship projection requires messages")
            user_text = ""
            for item in reversed(messages):
                if isinstance(item, dict) and item.get("role") == "user":
                    user_text = str(item.get("content") or "")
                    break
            relationship_event = build_user_signal_event(
                user_text,
                workspace_id=workspace_id,
                turn_id=str(payload.get("turn_id") or "").strip() or None,
            )
        if relationship_event is None:
            return
        writer = None
        if context is not None and getattr(context, "workspace_id", None) == workspace_id:
            writer = getattr(context, "extra", {}).get("relationship_event_writer")
        if writer is None:
            registered = _projection_runtime_context(workspace_id)
            if registered is not None and registered.workspace_id == workspace_id:
                writer = registered.relationship_event_writer
            elif registered is not None:
                writer_factory = registered.extras.get("relationship_writer_factory")
                if callable(writer_factory):
                    writer = writer_factory(workspace_id)
        if not callable(writer):
            raise RuntimeError(  # noqa: TRY004 - missing runtime dependency, not invalid input.
                "relationship projection writer is not available"
            )
        outcome = await asyncio.to_thread(writer, relationship_event)
        if inspect.isawaitable(outcome):
            await outcome

    async def _project_chat_exchange(event: dict[str, Any], context: Any | None) -> None:
        payload = event.get("payload")
        if not isinstance(payload, dict) or _projection_trigger(payload) not in {"http", "socket", "voice"}:
            return
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise TypeError("turn outbox chat projection requires messages")
        user_text = ""
        for item in reversed(messages):
            if isinstance(item, dict) and item.get("role") == "user":
                user_text = str(item.get("content") or "").strip()
                break
        assistant_text = str(payload.get("reply") or "").strip()
        if not user_text or not assistant_text:
            return
        workspace_id = str(payload.get("workspace_id") or "").strip() or None
        db_repo = None
        if context is not None and getattr(context, "workspace_id", None) == workspace_id:
            db_repo = getattr(context, "extra", {}).get("db_repo")
        if db_repo is None:
            registered = _projection_runtime_context(workspace_id)
            db_repo = registered.db_repo if registered is not None else None
        save_pair = getattr(db_repo, "save_message_pair", None)
        if not callable(save_pair):
            raise RuntimeError(  # noqa: TRY004 - missing runtime dependency, not invalid input.
                "chat projection repository is not available"
            )
        tool_trace: list[dict[str, Any]] = []
        memory_trace: list[dict[str, Any]] = []
        action_envelope = payload.get("action_envelope")
        actions = action_envelope.get("actions") if isinstance(action_envelope, dict) else None
        for action in actions if isinstance(actions, list) else []:
            if not isinstance(action, dict) or not isinstance(action.get("payload"), list):
                continue
            if action.get("type") == "tool_trace":
                tool_trace.extend(item for item in action["payload"] if isinstance(item, dict))
            elif action.get("type") == "memory_citation":
                memory_trace.extend(item for item in action["payload"] if isinstance(item, dict))
        saved_pair = await asyncio.to_thread(
            save_pair,
            str(payload.get("session_id") or ""),
            user_text,
            assistant_text,
            model=str(payload.get("model") or ""),
            workspace_id=workspace_id or "default",
            tool_trace=tool_trace,
            memory_trace=memory_trace,
            turn_idempotency_key=str(event.get("idempotency_key") or ""),
        )
        if (
            context is not None
            and getattr(context, "workspace_id", None) == workspace_id
            and isinstance(saved_pair, (list, tuple))
            and len(saved_pair) == 2
            and all(isinstance(record, dict) for record in saved_pair)
        ):
            context.extra["projected_message_ids"] = {
                "user_message_id": saved_pair[0].get("id"),
                "assistant_message_id": saved_pair[1].get("id"),
            }

    def _project_agent_trace(event: dict[str, Any], _context: Any | None) -> None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("turn outbox trace projection requires a payload")
        idempotency_key = str(event.get("idempotency_key") or "").strip()
        workspace_id = str(payload.get("workspace_id") or "default").strip() or "default"
        session_id = str(payload.get("session_id") or "").strip()
        request_id = str(payload.get("request_id") or "").strip() or None
        outcome = str(payload.get("outcome") or "completed").strip().lower()
        committed_at = float(payload.get("committed_at") or 0.0)
        trace_payload = {
            "workspace_id": workspace_id,
            "turn_id": str(payload.get("turn_id") or ""),
            "generation_id": str(payload.get("generation_id") or ""),
            "trigger": _projection_trigger(payload),
            "outcome": outcome,
            "retryable": bool(payload.get("retryable", False)),
            "configured_budget": dict(payload.get("configured_budget") or {}),
            "consumed_usage": dict(payload.get("consumed_usage") or {}),
            "tool_call_count": len(payload.get("tool_calls") or []),
            "commit_idempotency_key": idempotency_key,
        }
        # Newer producers may attach richer trace material. Keeping it inside
        # the commit record preserves backward compatibility with v1 payloads.
        explicit_trace = payload.get("agent_trace") or payload.get("trace_records")
        if isinstance(explicit_trace, (dict, list)):
            trace_payload["authoritative_trace"] = explicit_trace
        resolved_trace_store.append_once(
            "runtime_loop",
            {
                "timestamp": datetime.fromtimestamp(committed_at, tz=UTC).isoformat()
                if committed_at > 0
                else datetime.now(UTC).isoformat(),
                "session_id": session_id,
                "request_id": request_id,
                "stage": "turn_commit",
                "status": outcome,
                "summary": str(payload.get("reply") or "")[:240],
                "agent_id": "yuizaki.turn-commit",
                "agent_role": "authority",
                "data": trace_payload,
            },
            projection_key=f"{idempotency_key}:agent-trace",
        )

    def _project_job_terminal(event: dict[str, Any], _context: Any | None) -> None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("turn outbox job projection requires a payload")
        idempotency_key = str(event.get("idempotency_key") or "").strip()
        workspace_id = str(payload.get("workspace_id") or "default").strip() or "default"
        session_id = str(payload.get("session_id") or "").strip()
        request_id = str(payload.get("request_id") or idempotency_key).strip()
        turn_id = str(payload.get("turn_id") or f"turn:{request_id}").strip()
        explicit_outcome = payload.get("job_terminal") or payload.get("job_outcome")
        outcome_data = {
            key: value.strip()[:240]
            for key in _JOB_TERMINAL_PROJECTION_FIELDS
            if isinstance(explicit_outcome, dict)
            and isinstance((value := explicit_outcome.get(key)), str)
            and value.strip()
        }
        status = str(outcome_data.get("status") or payload.get("outcome") or "completed").strip().lower()
        status_aliases = {"ok": "completed", "error": "failed", "canceled": "cancelled"}
        status = status_aliases.get(status, status)
        if status not in {"completed", "failed", "cancelled", "interrupted", "unknown_effect"}:
            raise ValueError(f"unsupported authoritative job outcome: {status}")
        failure_projection = _bounded_terminal_descriptor(
            payload.get("failure"),
            fields=_FAILURE_PROJECTION_FIELDS,
        )
        recovery_projection = _bounded_terminal_descriptor(
            payload.get("recovery"),
            fields=_RECOVERY_PROJECTION_FIELDS,
        )
        if status == "unknown_effect":
            # Unknown effects are terminal and must never advertise resume.
            recovery_projection = None
        failure_category = str(
            (failure_projection or {}).get("category")
            or (failure_projection or {}).get("kind")
            or ""
        ).strip()
        failed_step = str(
            (failure_projection or {}).get("failed_step_id")
            or (failure_projection or {}).get("step_id")
            or (recovery_projection or {}).get("failed_step_id")
            or ""
        ).strip()
        completed_steps = (failure_projection or {}).get("completed_steps")
        failure_message = str((failure_projection or {}).get("message") or "").strip()
        trigger = _projection_trigger(payload)
        job_id = str(outcome_data.get("job_id") or payload.get("job_id") or "").strip()
        if not job_id and trigger == "scheduler" and turn_id.startswith("turn:"):
            job_id = turn_id.removeprefix("turn:")
        job_id = job_id or turn_id
        committed_at = float(payload.get("committed_at") or 0.0)
        resolved_job_event_log.append(
            workspace_id=workspace_id,
            session_id=session_id,
            turn_id=turn_id,
            job_id=job_id,
            conversation_id=str(outcome_data.get("conversation_id") or "").strip() or None,
            operation_id=str(outcome_data.get("operation_id") or "").strip() or None,
            run_id=str(outcome_data.get("run_id") or payload.get("run_id") or "").strip() or None,
            request_id=request_id,
            interruption_epoch=max(0, int(payload.get("interruption_epoch") or 0)),
            source=trigger,
            timestamp=committed_at,
            status=status,
            data={
                "trigger": trigger,
                "turnStage": "committed",
                "idempotencyKey": idempotency_key,
                "semanticFingerprint": str(payload.get("semantic_fingerprint") or ""),
                "generationId": str(payload.get("generation_id") or ""),
                "retryable": bool(payload.get("retryable", False)),
                "reply": str(payload.get("reply") or ""),
                "configuredBudget": dict(payload.get("configured_budget") or {}),
                "consumedUsage": dict(payload.get("consumed_usage") or {}),
                **outcome_data,
                **({"failure": failure_projection} if failure_projection else {}),
                **({"recovery": recovery_projection} if recovery_projection else {}),
                **({"failureCategory": failure_category[:120]} if failure_category else {}),
                **({"failedStep": failed_step[:120]} if failed_step else {}),
                **({"completedSteps": completed_steps} if completed_steps else {}),
                **({"error": failure_message[:240]} if failure_message else {}),
            },
            idempotency_key=f"{idempotency_key}:job-terminal",
        )

    turn_outbox_dispatcher = TurnOutboxDispatcher(
        resolved_turn_store,
        [
            TurnProjection("chat.exchange", _project_chat_exchange),
            TurnProjection("relationship.user-signal", _project_relationship_user_signal),
            TurnProjection("agent-trace.terminal", _project_agent_trace),
            TurnProjection("job.terminal", _project_job_terminal),
            TurnProjection("activity-frame.completed-turn-followup", activity_frame_service.project),
        ],
    )
    turn_outbox_worker = TurnOutboxWorker(turn_outbox_dispatcher)

    def _bind_registered_runtime_context(context: Any) -> Any:
        # Runtime context is opt-in per workspace until legacy entry points are
        # migrated; an unregistered workspace keeps the existing behavior.
        workspace_id = str(getattr(context, "workspace_id", None) or "workspace:default").strip()
        session_id = str(getattr(context, "session_id", "") or "").strip()
        request_id = str(getattr(context, "request_id", "") or f"request:{session_id}").strip()
        turn_id = str(getattr(context, "turn_id", "") or f"turn:{request_id}").strip()
        generation_id = str(getattr(context, "generation_id", "") or f"generation:{turn_id}").strip()
        interruption_epoch = getattr(context, "interruption_epoch", 0)
        if not all((workspace_id, session_id)):
            raise ValueError("desktop action binding requires a fully identified semantic turn")
        desktop_action_controller.bind_context(
            context,
            trusted_scope=DesktopActionScope(
                workspace_id=workspace_id,
                session_id=session_id,
                turn_id=turn_id,
                request_id=request_id,
                generation_id=generation_id,
                interruption_epoch=max(0, int(interruption_epoch)),
            ),
        )
        if resolved_runtime_context_registry.get(getattr(context, "workspace_id", None)) is not None:
            context = resolved_runtime_context_registry.bind_request(context)
        return context

    resolved_perception_registry = perception_registry or PerceptionProviderRegistry()
    turn_service = TurnService.from_pipeline(
        agent_pipeline,
        persist=resolved_turn_store.persist,
        load=resolved_turn_store.load,
        claim=resolved_turn_store.claim,
        renew_claim=resolved_turn_store.renew_claim,
        release_claim=resolved_turn_store.release_claim,
        dispatch=turn_outbox_dispatcher,
        bind_context=_bind_registered_runtime_context,
        perception_registry=resolved_perception_registry,
    )
    scheduler.turn_service = turn_service

    return AgentRuntime(
        tool_registry=tool_registry,
        mcp_manager=mcp_manager,
        policy_engine=resolved_policy_engine,
        tool_executor=tool_executor,
        step_executor=step_executor,
        agent_pipeline=agent_pipeline,
        trace_store=resolved_trace_store,
        plugin_manager=plugin_manager,
        schedule_store=schedule_store,
        scheduler=scheduler,
        turn_service=turn_service,
        desktop_adapter=resolved_desktop_adapter,
        desktop_action_controller=desktop_action_controller,
        computer_use_controller=computer_use_controller,
        runtime_context_registry=resolved_runtime_context_registry,
        perception_registry=resolved_perception_registry,
        turn_store=resolved_turn_store,
        turn_outbox_dispatcher=turn_outbox_dispatcher,
        turn_outbox_worker=turn_outbox_worker,
        activity_frame_service=activity_frame_service,
    )
