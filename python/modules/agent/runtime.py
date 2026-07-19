from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .agent_trace_store import AgentTraceStore
from .default_tools import register_default_tools
from .mcp_manager import MCPManager
from .pipeline import AgentPipeline
from .policy_engine import PolicyEngine
from .schedule_store import ScheduleStore
from .scheduler import AgentScheduler
from .step_executor import StepExecutor
from .tool_executor import ToolExecutor
from .tool_registry import ToolRegistry
from ..agent_plugins.manager import PluginManager


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


def create_agent_runtime(
    *,
    schedule_context_factory: Callable[[Any], Any],
    trace_store: AgentTraceStore | None = None,
    policy_engine: PolicyEngine | None = None,
    tool_outcome_observer: Callable[[bool], None] | None = None,
) -> AgentRuntime:
    tool_registry = ToolRegistry()
    register_default_tools(tool_registry)

    mcp_manager = MCPManager()
    mcp_manager.register_tools(tool_registry)

    resolved_policy_engine = policy_engine or PolicyEngine()
    resolved_trace_store = trace_store or AgentTraceStore()
    tool_executor = ToolExecutor(tool_registry, resolved_policy_engine, tool_outcome_observer)
    step_executor = StepExecutor()
    agent_pipeline = AgentPipeline()
    plugin_manager = PluginManager()
    schedule_store = ScheduleStore()
    scheduler = AgentScheduler(
        store=schedule_store,
        pipeline=agent_pipeline,
        context_factory=schedule_context_factory,
    )

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
    )
