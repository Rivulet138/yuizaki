from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class StepConditionRecord:
    source_step_id: str = ""
    mode: str = "continue_if"
    status_in: list[str] = field(default_factory=list)
    status_not_in: list[str] = field(default_factory=list)
    content_contains: list[str] = field(default_factory=list)
    error_contains: list[str] = field(default_factory=list)
    all_of: list["StepConditionRecord"] = field(default_factory=list)
    any_of: list["StepConditionRecord"] = field(default_factory=list)
    none_of: list["StepConditionRecord"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ActionType = Literal["reply", "pet_control", "tool_trace"]


@dataclass
class CharacterAction:
    type: ActionType
    content: str | None = None
    payload: Any | None = None
    schema_version: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


@dataclass
class ActionEnvelope:
    version: int
    request_id: str
    source: str
    reply: str
    schema_version: str = "yuizaki.action-envelope.v1"
    actions: list[CharacterAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "source": self.source,
            "reply": self.reply,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass
class PlannerStepRecord:
    id: str = ""
    title: str = ""
    kind: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    condition: StepConditionRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.condition is not None:
            data["condition"] = self.condition.to_dict()
        return data


@dataclass
class PlannerTrace:
    timestamp: str
    session_id: str
    goal: str
    mode: str
    steps: list[PlannerStepRecord]
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "goal": self.goal,
            "mode": self.mode,
            "steps": [step.to_dict() for step in self.steps],
            "request_id": self.request_id,
        }


@dataclass
class SchedulerRunRecord:
    timestamp: str
    task_id: str
    task_name: str
    mode: str
    status: str
    summary: str | None = None
    request_id: str | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolTrace:
    timestamp: str
    tool: str
    args: dict[str, Any]
    success: bool
    content: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepResultRecord:
    step_id: str
    kind: str
    status: str
    title: str
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    condition: StepConditionRecord | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    success: bool | None = None
    content: str | None = None
    error: str | None = None
    task_id: str | None = None
    mode: str | None = None
    reply_preview: str | None = None
    tool_calls_count: int | None = None
    has_pet_control: bool | None = None
    retry_count: int | None = None
    rollback_status: str | None = None
    rollback_target: str | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None
    capability_id: str | None = None
    capability_type: str | None = None
    capability_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.condition is not None:
            data["condition"] = self.condition.to_dict()
        return data


@dataclass
class StepExecutionRecord:
    timestamp: str
    kind: str
    status: str
    step_id: str | None = None
    title: str | None = None
    depends_on: list[str] | None = None
    condition: StepConditionRecord | None = None
    prompt: str | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    success: bool | None = None
    error: str | None = None
    task_id: str | None = None
    mode: str | None = None
    reply_preview: str | None = None
    tool_calls_count: int | None = None
    has_pet_control: bool | None = None
    retry_count: int | None = None
    rollback_status: str | None = None
    rollback_target: str | None = None
    request_id: str | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None
    capability_id: str | None = None
    capability_type: str | None = None
    capability_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.condition is not None:
            data["condition"] = self.condition.to_dict()
        return data


@dataclass
class PermissionAuditRecord:
    timestamp: str
    tool_name: str | None = None
    capability_id: str | None = None
    capability_type: str | None = None
    capability_kind: str | None = None
    remember_scope: str | None = None
    decision: str = "unknown"
    risk_level: str | None = None
    request_id: str | None = None
    remember: bool | None = None
    requires_approval: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginTraceRecord:
    timestamp: str
    plugin_id: str
    hook: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginSnapshot:
    id: str
    name: str
    version: str
    enabled: bool
    loaded: bool
    error: str | None = None
    config: dict[str, Any] | None = None
    config_schema: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MCPInventoryItem:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MCPHistoryEntry:
    timestamp: str
    event: str
    status: str = "info"
    detail: str = ""
    transport: str | None = None
    tool: str | None = None
    request_id: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    session_id: str | None = None
    pending_requests: int | None = None
    total_calls: int | None = None
    total_failures: int | None = None
    args_keys: list[str] | None = None
    output_chars: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MCPServerConfigSnapshot:
    name: str
    base_url: str
    transport: str
    enabled: bool
    command: str | None = None
    args: list[str] | None = None
    env_keys: list[str] | None = None
    header_keys: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MCPServerStatusSnapshot:
    enabled: bool
    ok: bool
    status_code: int | None = None
    message: str | None = None
    transport: str | None = None
    connected: bool | None = None
    pending_requests: int | None = None
    total_calls: int | None = None
    total_failures: int | None = None
    reconnect_count: int | None = None
    last_error: str | None = None
    session_id: str | None = None
    history: list[MCPHistoryEntry] | None = None
    tools_count: int | None = None
    resources_count: int | None = None
    prompts_count: int | None = None
    tools: list[MCPInventoryItem] | None = None
    resources: list[MCPInventoryItem] | None = None
    prompts: list[MCPInventoryItem] | None = None
    inventory_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeLoopRecord:
    timestamp: str
    session_id: str
    request_id: str | None = None
    stage: str = "observe"
    status: str = "ok"
    summary: str = ""
    agent_id: str | None = None
    agent_role: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MCPSnapshot:
    servers: dict[str, MCPServerConfigSnapshot]
    status: dict[str, MCPServerStatusSnapshot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "servers": {name: server.to_dict() for name, server in self.servers.items()},
            "status": {name: status.to_dict() for name, status in self.status.items()},
        }
