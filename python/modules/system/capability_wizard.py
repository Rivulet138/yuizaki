"""First-run capability assessment with explicit repair guidance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

CapabilityStatus = Literal["ready", "degraded", "unavailable"]


@dataclass(frozen=True)
class CapabilityCheck:
    capability_id: str
    label: str
    status: CapabilityStatus
    message: str
    repair_action: str | None = None
    required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id is required")
        if self.status == "ready" and self.repair_action:
            raise ValueError("ready capability cannot have a repair action")
        if self.status != "ready" and not self.message.strip():
            raise ValueError("degraded capability requires an actionable message")


@dataclass(frozen=True)
class CapabilityWizardSnapshot:
    checks: tuple[CapabilityCheck, ...]
    preset: str = "local_private"

    @property
    def ready(self) -> bool:
        return not any(check.required and check.status == "unavailable" for check in self.checks)

    @property
    def status(self) -> CapabilityStatus:
        if any(check.status == "unavailable" for check in self.checks):
            return "unavailable"
        if any(check.status == "degraded" for check in self.checks):
            return "degraded"
        return "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "status": self.status,
            "ready": self.ready,
            "checks": [
                {
                    "id": check.capability_id,
                    "label": check.label,
                    "status": check.status,
                    "message": check.message,
                    "repairAction": check.repair_action,
                    "required": check.required,
                    "metadata": dict(check.metadata),
                }
                for check in self.checks
            ],
        }


def build_capability_snapshot(
    checks: list[CapabilityCheck] | tuple[CapabilityCheck, ...],
    *,
    preset: str = "local_private",
) -> CapabilityWizardSnapshot:
    return CapabilityWizardSnapshot(tuple(checks), preset=preset.strip() or "local_private")


__all__ = ["CapabilityCheck", "CapabilityWizardSnapshot", "build_capability_snapshot"]
