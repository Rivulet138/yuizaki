# pyright: reportImportCycles=false

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from .agent_trace_store import AgentTraceStore
    from ..agent_plugins.manager import PluginManager
    from .scheduler import AgentScheduler
    from .step_executor import StepExecutor
    from .tool_executor import ToolExecutor
    from .tool_registry import ToolRegistry


AutonomyMode = Literal["companion", "assistant", "executor", "reflector", "silent"]
VALID_AUTONOMY_MODES: tuple[AutonomyMode, ...] = (
    "companion", "assistant", "executor", "reflector", "silent",
)


def coerce_autonomy_mode(value: object) -> AutonomyMode:
    mode = str(value or "companion")
    if mode in VALID_AUTONOMY_MODES:
        return mode  # type: ignore[return-value]
    return "companion"


@dataclass
class AgentRuntimeBindings:
    db_repo: Any | None = None
    relationship_event_writer: Callable[[dict[str, Any]], Any] | None = None
    relationship_history: list[dict[str, Any]] = field(default_factory=list)
    relationship_summary: dict[str, Any] = field(default_factory=dict)
    retrieved_chunks: list[str] = field(default_factory=list)


def bind_runtime_bindings(
    ctx: "AgentRequestContext",
    *,
    db_repo: Any | None = None,
    relationship_event_writer: Callable[[dict[str, Any]], Any] | None = None,
    relationship_history: list[dict[str, Any]] | None = None,
    relationship_summary: dict[str, Any] | None = None,
    retrieved_chunks: list[str] | None = None,
) -> "AgentRequestContext":
    bindings = AgentRuntimeBindings(
        db_repo=db_repo,
        relationship_event_writer=relationship_event_writer,
        relationship_history=list(relationship_history or []),
        relationship_summary=dict(relationship_summary or {}),
        retrieved_chunks=list(retrieved_chunks or []),
    )
    ctx.extra["runtime_bindings"] = bindings
    ctx.extra["db_repo"] = bindings.db_repo
    ctx.extra["relationship_event_writer"] = bindings.relationship_event_writer
    ctx.extra["relationship_history"] = bindings.relationship_history
    ctx.extra["relationship_summary"] = bindings.relationship_summary
    ctx.extra["retrieved_chunks"] = bindings.retrieved_chunks
    return ctx


def get_runtime_bindings(ctx: "AgentRequestContext") -> AgentRuntimeBindings:
    existing = ctx.extra.get("runtime_bindings")
    if isinstance(existing, AgentRuntimeBindings):
        return existing
    bindings = AgentRuntimeBindings(
        db_repo=ctx.extra.get("db_repo"),
        relationship_event_writer=ctx.extra.get("relationship_event_writer"),
        relationship_history=list(ctx.extra.get("relationship_history") or []),
        relationship_summary=dict(ctx.extra.get("relationship_summary") or {}),
        retrieved_chunks=list(ctx.extra.get("retrieved_chunks") or []),
    )
    ctx.extra["runtime_bindings"] = bindings
    return bindings


@dataclass
class AgentRequestContext:
    sid: str
    session_id: str
    messages: list[dict[str, Any]]
    workspace_id: str | None = None
    request_id: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    max_tokens: int = 8192
    model: str | None = None
    reasoning_effort: str | None = None
    thinking_mode: str | None = None
    response_mode: str = "balanced"
    mcp_enabled: bool | None = None
    web_search_enabled: bool | None = None
    prompt_profile: dict[str, Any] | None = None
    pet_control_context: dict[str, Any] | None = None
    llm_client: Any | None = None
    generation_mgr: Any | None = None
    tool_registry: 'ToolRegistry | None' = None
    tool_executor: 'ToolExecutor | None' = None
    step_executor: 'StepExecutor | None' = None
    scheduler: 'AgentScheduler | None' = None
    trace_store: 'AgentTraceStore | None' = None
    plugin_manager: 'PluginManager | None' = None
    permission_request_cb: Callable[..., Any] | None = None
    permission_scope: str | None = None
    autonomy_mode: AutonomyMode | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mode = coerce_autonomy_mode(
            self.autonomy_mode if self.autonomy_mode is not None else self.extra.get("autonomy_mode")
        )
        self.autonomy_mode = mode
        self.extra.pop("autonomy_mode", None)


@dataclass
class AgentPipelineResult:
    reply: str
    pet_control: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    action_envelope: dict[str, Any] | None = None
