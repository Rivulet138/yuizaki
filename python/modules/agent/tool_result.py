from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .permission_receipt import PermissionReceipt


ToolSource = Literal["builtin", "mcp", "plugin"]
RiskLevel = Literal["safe", "low", "medium", "high", "critical"]


@dataclass
class ToolResultEnvelope:
    success: bool
    content: str
    source: ToolSource
    tool_name: str
    data: Any | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    permission_receipt: PermissionReceipt | None = None
