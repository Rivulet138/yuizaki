from __future__ import annotations

from dataclasses import dataclass

from .interpret import InterpretResult


@dataclass(frozen=True)
class RouteDecision:
    owner_agent_id: str
    owner_agent_role: str
    route_reason: str


def companion_orchestrator_route(
    reason: str = "Default companion orchestration path",
) -> RouteDecision:
    return RouteDecision(
        owner_agent_id="yuizaki.companion-orchestrator",
        owner_agent_role="orchestrator",
        route_reason=reason,
    )


def task_router_route(
    reason: str = "Task execution routed to capability/task router",
) -> RouteDecision:
    return RouteDecision(
        owner_agent_id="yuizaki.task-router",
        owner_agent_role="router",
        route_reason=reason,
    )


def memory_reflector_route(
    reason: str = "Reflection and relationship updates routed to memory reflector",
) -> RouteDecision:
    return RouteDecision(
        owner_agent_id="yuizaki.memory-reflector",
        owner_agent_role="reflector",
        route_reason=reason,
    )


def resolve_step_route(kind: str) -> RouteDecision:
    normalized = (kind or "").strip().lower()
    if normalized == "tool":
        return task_router_route("Tool-like prompt routed to capability execution")
    if normalized == "schedule":
        return task_router_route("Schedule creation routed to task router")
    if normalized == "analysis":
        return companion_orchestrator_route("Planning and interpretation stay in orchestrator")
    if normalized == "join":
        return companion_orchestrator_route("Branch merge and final synthesis stay in orchestrator")
    return companion_orchestrator_route()


def resolve_schedule_route(mode: str) -> RouteDecision:
    normalized = (mode or "").strip().lower()
    if normalized == "interval":
        return task_router_route("Scheduled interval task owned by task-router")
    return task_router_route("Scheduled once task owned by task-router")


def resolve_route_from_intent(
    interpret: InterpretResult,
    relationship_stage: str = "warming",
    autonomy_mode: str = "companion",
    recent_signal_kinds: list[str] | None = None,
    has_workspace_tool_preset: bool = False,
) -> RouteDecision:
    signals = [str(item) for item in (recent_signal_kinds or []) if item]
    if interpret.intent == "schedule":
        return task_router_route(f"Scheduled intent detected (urgency={interpret.urgency})")
    if interpret.intent == "task" or autonomy_mode == "executor":
        suffix = " with workspace tool preset" if has_workspace_tool_preset else ""
        return task_router_route(f"Tool/task intent from interpret layer{suffix}")
    if interpret.intent == "reflect" or autonomy_mode == "reflector":
        return memory_reflector_route("Emotional/reflect signal from interpret layer")
    if any(kind in signals for kind in ["support_request", "comfort_event"]):
        return companion_orchestrator_route(
            f"Companion path boosted by recent support signals (stage={relationship_stage}, autonomy={autonomy_mode})"
        )
    return companion_orchestrator_route(
        f"Companion path: intent={interpret.intent}, stage={relationship_stage}, autonomy={autonomy_mode}"
    )


def system_prompt_for_agent_role(role: str | None) -> str:
    normalized = (role or "orchestrator").strip().lower()
    if normalized == "router":
        return "你当前扮演 task-router。优先选择直接、可执行、低歧义的任务完成路径，并尽量利用已有 capability。"
    if normalized == "reflector":
        return "你当前扮演 memory-reflector。优先总结结果、抽取经验、收敛关系与记忆更新信号。"
    return "你当前扮演 companion-orchestrator。优先保持陪伴感、上下文连续性和任务协作之间的平衡。"
