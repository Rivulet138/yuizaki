from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .permission_receipt import PermissionReceipt

ToolSource = Literal["builtin", "mcp", "plugin"]
RiskLevel = Literal["safe", "low", "medium", "high", "critical"]
EffectOutcome = Literal["known_success", "known_failure", "unknown_effect"]


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
    outcome: EffectOutcome | None = None
    retryable: bool | None = None

    def __post_init__(self) -> None:
        resolved_outcome: EffectOutcome = self.outcome or (
            "known_success" if self.success else "known_failure"
        )
        if resolved_outcome == "known_success" and not self.success:
            raise ValueError("known_success requires success=True")
        if resolved_outcome != "known_success" and self.success:
            raise ValueError(f"{resolved_outcome} requires success=False")
        resolved_retryable = (
            resolved_outcome == "known_failure"
            if self.retryable is None
            else bool(self.retryable)
        )
        if resolved_outcome == "unknown_effect" and resolved_retryable:
            raise ValueError("unknown_effect is terminal and cannot be retryable")
        if (
            self.permission_receipt is not None
            and self.permission_receipt.retryable is False
        ):
            resolved_retryable = False
        self.outcome = resolved_outcome
        self.retryable = resolved_retryable
