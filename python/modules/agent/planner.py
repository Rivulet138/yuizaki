from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .interpret import InterpretResult
from .route_policy import resolve_step_route

StepKind = Literal["analysis", "agent", "tool", "schedule", "join"]
PREDICATE_OPERATORS = {
    "status_in",
    "status_not_in",
    "content_contains",
    "error_contains",
    "all",
    "any",
    "none",
}
RETRY_OWNERS = {"step_executor", "provider", "tool_adapter", "none"}


class PlanValidationError(ValueError):
    """Raised when a plan cannot be safely executed."""


def _strict_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise PlanValidationError(f"{path} contains invalid UTF-8 text") from exc
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise PlanValidationError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PlanValidationError(f"{path} contains a non-string object key")
            normalized[key] = _strict_json_value(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, list):
        return [
            _strict_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise PlanValidationError(
        f"{path} contains a non-JSON value of type {type(value).__name__}"
    )


def canonical_json_bytes(value: Any, *, path: str = "value") -> bytes:
    """Encode a strict JSON value into deterministic UTF-8 bytes."""

    normalized = _strict_json_value(value, path=path)
    try:
        text = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise PlanValidationError(f"{path} is not strict canonical JSON") from exc


def strict_json_loads(value: str | bytes, *, path: str = "value") -> Any:
    """Decode strict JSON, rejecting extensions and duplicate object keys."""

    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-finite number {constant}")

    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = item
        return result

    try:
        text = value.decode("utf-8", errors="strict") if isinstance(value, bytes) else value
        decoded = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=object_from_pairs,
        )
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanValidationError(f"{path} is not strict JSON") from exc
    return _strict_json_value(decoded, path=path)


def _legacy_integer(value: Any, *, path: str) -> int:
    """Normalize the explicit v1 adapter without accepting lossy coercions."""

    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value)
    raise PlanValidationError(f"{path} must be an integer")


def _legacy_timeout(value: Any, *, path: str) -> int | float:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, str):
        if re.fullmatch(r"[+-]?\d+", value.strip()):
            return int(value)
        try:
            parsed = float(value.strip())
        except ValueError as exc:
            raise PlanValidationError(f"{path} must be a finite number") from exc
        if math.isfinite(parsed):
            return parsed
    raise PlanValidationError(f"{path} must be a finite number")


@dataclass
class PredicateNode:
    """Closed, data-only predicate AST used by plan success criteria.

    The node is deliberately not executable Python.  Runtime evaluation is
    implemented by the step executor using an allow-listed operator set.
    """

    op: str
    source_step_id: str | None = None
    values: list[str] = field(default_factory=list)
    children: list[PredicateNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"op": self.op}
        if self.source_step_id:
            data["source_step_id"] = self.source_step_id
        if self.values:
            data["values"] = list(self.values)
        if self.children:
            data["children"] = [child.to_dict() for child in self.children]
        return data


@dataclass
class PlanStep:
    id: str
    title: str
    # ``action`` was the pre-typed default. It is normalized to ``agent`` in
    # __post_init__ so persisted legacy plans retain their behavior.
    kind: StepKind | str = "action"
    description: str = ""
    payload: dict[str, Any] | None = None
    depends_on: list[str] = field(default_factory=list)
    condition: StepCondition | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None
    # Typed tool contract.  ``payload.prompt`` remains accepted during the
    # migration window, but new plans should populate these fields directly.
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int | float | None = None
    retry_budget: int = 0
    idempotency_key: str | None = None
    success_criteria: PredicateNode | dict[str, Any] | None = None
    retry_owner: str = "step_executor"
    plan_version: int = 2
    compatibility_trace: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind == "action":
            self.kind = "agent"
        if self.payload is not None and not isinstance(self.payload, dict):
            raise PlanValidationError("step payload must be an object")
        payload = self.payload or {}
        legacy_prompt = bool(payload.get("prompt"))
        # Backward-compatible adapter: copy the old shape into typed fields,
        # while retaining payload for old tracing/transport consumers.
        if self.tool_name is None and payload.get("tool_name"):
            self.tool_name = str(payload["tool_name"])
        if not self.arguments and isinstance(payload.get("arguments"), dict):
            self.arguments = dict(payload["arguments"])
        if self.timeout_seconds is None and payload.get("timeout_seconds") is not None:
            self.timeout_seconds = _legacy_timeout(
                payload["timeout_seconds"], path="legacy timeout_seconds"
            )
        if self.retry_budget == 0 and payload.get("retry_budget") is not None:
            self.retry_budget = _legacy_integer(
                payload["retry_budget"], path="legacy retry_budget"
            )
        if self.idempotency_key is None and "idempotency_key" in payload:
            self.idempotency_key = payload["idempotency_key"]
        if self.success_criteria is None and payload.get("success_criteria") is not None:
            self.success_criteria = payload["success_criteria"]
        if not self.description and payload.get("prompt"):
            self.description = str(payload["prompt"])
        if legacy_prompt and self.kind == "tool":
            self.plan_version = 1
            self.compatibility_trace = {
                "adapter": "legacy_prompt",
                "from_version": 1,
                "to_version": 2,
                "preserved_payload": True,
            }
        elif self.kind == "tool" and type(self) is PlanStep and self.tool_name is None:
            self.plan_version = 1
            self.compatibility_trace = {
                "adapter": "legacy_untyped_tool",
                "from_version": 1,
                "to_version": 2,
                "preserved_payload": True,
            }
        if self.kind == "tool" and self.plan_version >= 2 and (self.tool_name is not None or self.arguments or type(self) is not PlanStep):
            # Typed tool steps always have a closed execution contract. These
            # defaults keep source-compatible constructors deterministic.
            if self.timeout_seconds is None:
                self.timeout_seconds = 30
            if self.idempotency_key is None:
                self.idempotency_key = f"plan:{self.id}"
            if self.success_criteria is None:
                self.success_criteria = {"op": "status_in", "values": ["ok", "created"]}
            self.retry_owner = self.retry_owner or "step_executor"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if isinstance(self.success_criteria, PredicateNode):
            data["success_criteria"] = self.success_criteria.to_dict()
        return data


@dataclass(frozen=True)
class _TypedStepBase:
    id: str
    title: str
    kind: StepKind = field(default="agent", init=False)
    description: str = ""
    payload: dict[str, Any] | None = None
    depends_on: list[str] = field(default_factory=list)
    condition: StepCondition | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None
    success_criteria: PredicateNode | dict[str, Any] | None = None
    plan_version: int = 2
    compatibility_trace: dict[str, Any] | None = None
    expected_kind: ClassVar[str] = "agent"
    legacy_payload_keys: ClassVar[frozenset[str]] = frozenset({"prompt"})

    def __post_init__(self) -> None:
        if self.kind != self.expected_kind:
            raise PlanValidationError(f"{type(self).__name__} requires kind={self.expected_kind!r}")
        if self.payload is not None and not isinstance(self.payload, dict):
            raise PlanValidationError("step payload must be an object")
        if self.payload is not None:
            if self.plan_version != 1:
                raise PlanValidationError("typed v2 steps do not accept payload; use plan_version=1 legacy adapter")
            unsupported = set(self.payload) - self.legacy_payload_keys
            if unsupported:
                raise PlanValidationError(
                    f"legacy {self.kind} payload contains unsupported fields: {sorted(unsupported)!r}"
                )
            if not self.description and self.payload.get("prompt"):
                object.__setattr__(self, "description", str(self.payload["prompt"]))
            if self.compatibility_trace is None:
                object.__setattr__(self, "compatibility_trace", {
                    "adapter": "legacy_typed_payload",
                    "from_version": 1,
                    "to_version": 2,
                    "preserved_payload": True,
                })

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if isinstance(self.success_criteria, PredicateNode):
            data["success_criteria"] = self.success_criteria.to_dict()
        return data


@dataclass(frozen=True)
class AnalysisStep(_TypedStepBase):
    kind: Literal["analysis"] = field(default="analysis", init=False)
    max_input_chars: int = 32768
    max_output_chars: int = 8192
    expected_kind: ClassVar[str] = "analysis"


@dataclass(frozen=True)
class AgentStep(_TypedStepBase):
    kind: Literal["agent"] = field(default="agent", init=False)
    model: str | None = None
    max_tokens: int = 8192
    capability_budget: int = 16
    expected_kind: ClassVar[str] = "agent"


@dataclass(frozen=True)
class ToolStep(_TypedStepBase):
    kind: Literal["tool"] = field(default="tool", init=False)
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int | float = 30
    retry_budget: int = 0
    retry_owner: str = "step_executor"
    idempotency_key: str | None = None
    expected_kind: ClassVar[str] = "tool"
    legacy_payload_keys: ClassVar[frozenset[str]] = frozenset({
        "prompt", "tool_name", "arguments", "timeout_seconds", "retry_budget",
        "retry_owner", "idempotency_key", "success_criteria",
    })

    def __post_init__(self) -> None:
        super().__post_init__()
        payload = self.payload or {}
        if self.plan_version == 1:
            if self.tool_name is None and payload.get("tool_name"):
                object.__setattr__(self, "tool_name", str(payload["tool_name"]))
            if not self.arguments and isinstance(payload.get("arguments"), dict):
                object.__setattr__(self, "arguments", dict(payload["arguments"]))
            if payload.get("timeout_seconds") is not None and self.timeout_seconds == 30:
                object.__setattr__(self, "timeout_seconds", _legacy_timeout(
                    payload["timeout_seconds"], path="legacy timeout_seconds"
                ))
            if payload.get("retry_budget") is not None and self.retry_budget == 0:
                object.__setattr__(self, "retry_budget", _legacy_integer(
                    payload["retry_budget"], path="legacy retry_budget"
                ))
            if payload.get("retry_owner") and self.retry_owner == "step_executor":
                object.__setattr__(self, "retry_owner", str(payload["retry_owner"]))
            if self.idempotency_key is None and "idempotency_key" in payload:
                object.__setattr__(self, "idempotency_key", payload["idempotency_key"])
            if self.success_criteria is None and payload.get("success_criteria") is not None:
                object.__setattr__(self, "success_criteria", payload["success_criteria"])
        if self.idempotency_key is None:
            object.__setattr__(self, "idempotency_key", f"plan:{self.id}")
        if self.success_criteria is None:
            object.__setattr__(
                self,
                "success_criteria",
                {"op": "status_in", "values": ["ok", "created"]},
            )


@dataclass(frozen=True)
class ScheduleStep(_TypedStepBase):
    kind: Literal["schedule"] = field(default="schedule", init=False)
    schedule_mode: Literal["once", "interval"] = "once"
    prompt: str = ""
    run_after_seconds: int = 0
    interval_seconds: int = 60
    timezone: str = "UTC"
    cancellation_key: str | None = None
    expected_kind: ClassVar[str] = "schedule"
    legacy_payload_keys: ClassVar[frozenset[str]] = frozenset({
        "mode", "prompt", "run_after_seconds", "interval_seconds", "timezone",
        "cancellation_key",
    })

    def __post_init__(self) -> None:
        super().__post_init__()
        payload = self.payload or {}
        if self.plan_version == 1:
            if payload.get("mode"):
                object.__setattr__(self, "schedule_mode", str(payload["mode"]))
            if payload.get("prompt") and not self.prompt:
                object.__setattr__(self, "prompt", str(payload["prompt"]))
            if payload.get("run_after_seconds") is not None:
                object.__setattr__(self, "run_after_seconds", int(payload["run_after_seconds"]))
            if payload.get("interval_seconds") is not None:
                object.__setattr__(self, "interval_seconds", int(payload["interval_seconds"]))
            if payload.get("timezone"):
                object.__setattr__(self, "timezone", str(payload["timezone"]))
            if payload.get("cancellation_key"):
                object.__setattr__(self, "cancellation_key", str(payload["cancellation_key"]))
        object.__setattr__(self, "cancellation_key", self.cancellation_key or f"plan:{self.id}")


@dataclass(frozen=True)
class JoinStep(_TypedStepBase):
    kind: Literal["join"] = field(default="join", init=False)
    merge_policy: Literal["any_success", "all_success"] = "any_success"
    max_merged_chars: int = 16384
    expected_kind: ClassVar[str] = "join"


PlanStepUnion = AnalysisStep | AgentStep | ToolStep | ScheduleStep | JoinStep
AnyPlanStep = PlanStep | PlanStepUnion


@dataclass
class StepCondition:
    source_step_id: str = ""
    mode: str = "continue_if"
    status_in: list[str] = field(default_factory=list)
    status_not_in: list[str] = field(default_factory=list)
    content_contains: list[str] = field(default_factory=list)
    error_contains: list[str] = field(default_factory=list)
    all_of: list[StepCondition] = field(default_factory=list)
    any_of: list[StepCondition] = field(default_factory=list)
    none_of: list[StepCondition] = field(default_factory=list)
    # Optional closed predicate form. Existing fields are retained for wire
    # compatibility and are treated as an equivalent allow-listed AST.
    predicate: PredicateNode | dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if isinstance(self.predicate, PredicateNode):
            data["predicate"] = self.predicate.to_dict()
        return data

    def to_predicate(self) -> PredicateNode | dict[str, Any] | None:
        if self.predicate is not None:
            return self.predicate
        children: list[PredicateNode | dict[str, Any]] = []
        for op, values in (
            ("status_in", self.status_in),
            ("status_not_in", self.status_not_in),
            ("content_contains", self.content_contains),
            ("error_contains", self.error_contains),
        ):
            if values:
                children.append(PredicateNode(op=op, source_step_id=self.source_step_id, values=list(values)))
        for op, conditions in (("all", self.all_of), ("any", self.any_of), ("none", self.none_of)):
            nested = [item.to_predicate() for item in conditions]
            if nested:
                children.append({"op": op, "children": [item for item in nested if item is not None]})
        if not children:
            return None
        return children[0] if len(children) == 1 else {"op": "all", "children": children}


PlanMode = Literal["immediate", "scheduled_once", "scheduled_interval", "mixed"]
PlanOutcome = Literal["execute", "clarification_required", "refused"]


@dataclass
class PlanResult:
    goal: str
    mode: PlanMode = "immediate"
    steps: list[PlanStepUnion] = field(default_factory=list)
    delay_seconds: int | None = None
    interval_seconds: int | None = None
    immediate_steps: list[PlanStepUnion] = field(default_factory=list)
    scheduled_steps: list[PlanStepUnion] = field(default_factory=list)
    outcome: PlanOutcome = "execute"
    clarification_question: str | None = None
    refusal_reason: str | None = None
    compatibility_trace: dict[str, Any] | None = None

    def validate(self, *, max_steps: int = 32, max_retry_budget: int = 8, max_timeout_seconds: int = 900) -> None:
        validate_plan(
            self.steps,
            max_steps=max_steps,
            max_retry_budget=max_retry_budget,
            max_timeout_seconds=max_timeout_seconds,
        )


def _validate_predicate(
    value: Any,
    *,
    path: str = "predicate",
    known_step_ids: set[str] | None = None,
    allow_implicit_source: bool = False,
) -> None:
    if value is None:
        return
    if isinstance(value, PredicateNode):
        op = value.op
        source = value.source_step_id
        values = value.values
        children = value.children
    elif isinstance(value, Mapping):
        allowed = {"op", "source_step_id", "values", "children"}
        unknown = set(value) - allowed
        if unknown:
            raise PlanValidationError(f"{path} contains unsupported fields: {sorted(unknown)}")
        op = value.get("op")
        source = value.get("source_step_id")
        values = value.get("values", [])
        children = value.get("children", [])
    else:
        raise PlanValidationError(f"{path} must be a predicate object")
    if op not in PREDICATE_OPERATORS:
        raise PlanValidationError(f"{path}.op is not allow-listed: {op!r}")
    if source is not None and not isinstance(source, str):
        raise PlanValidationError(f"{path}.source_step_id must be a string")
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise PlanValidationError(f"{path}.values must be a list of strings")
    if op in {"all", "any", "none"}:
        if source is not None or values:
            raise PlanValidationError(f"{path} combinators cannot contain source_step_id or values")
        if not isinstance(children, list) or not children:
            raise PlanValidationError(f"{path}.children must be a non-empty list")
    else:
        if children:
            raise PlanValidationError(f"{path} leaf predicates cannot contain children")
        if not source and not allow_implicit_source:
            raise PlanValidationError(f"{path}.source_step_id is required")
        if not values:
            raise PlanValidationError(f"{path}.values must be non-empty")
        if source and known_step_ids is not None and source not in known_step_ids:
            raise PlanValidationError(f"{path} references unknown step {source}")
    for index, child in enumerate(children):
        _validate_predicate(
            child,
            path=f"{path}.children[{index}]",
            known_step_ids=known_step_ids,
            allow_implicit_source=allow_implicit_source,
        )


def validate_plan(
    steps: Sequence[AnyPlanStep],
    *,
    max_steps: int = 32,
    max_retry_budget: int = 8,
    max_timeout_seconds: int = 900,
    max_analysis_input_chars: int = 262144,
    max_analysis_output_chars: int = 65536,
    max_agent_tokens: int = 65536,
    max_agent_capability_budget: int = 128,
    max_schedule_seconds: int = 31536000,
    max_join_chars: int = 131072,
    allow_external_dependencies: bool = False,
) -> None:
    """Validate schema, dependencies, predicates and execution budgets.

    This function is intentionally deterministic and side-effect free. It is
    the single gate used before execution; no expression is evaluated.
    """
    if not isinstance(steps, list):
        raise PlanValidationError("plan.steps must be a list")
    if len(steps) > max_steps:
        raise PlanValidationError(f"plan exceeds step budget ({len(steps)} > {max_steps})")
    ids: set[str] = set()
    step_map: dict[str, AnyPlanStep] = {}
    total_retries = 0
    total_timeout = 0
    total_analysis_input = 0
    total_analysis_output = 0
    total_agent_tokens = 0
    total_agent_capabilities = 0
    total_schedule_seconds = 0
    total_join_chars = 0
    for index, step in enumerate(steps):
        if not isinstance(step, (PlanStep, _TypedStepBase)):
            raise PlanValidationError(f"steps[{index}] is not a plan step")
        if step.kind not in {"analysis", "agent", "tool", "schedule", "join"}:
            raise PlanValidationError(f"steps[{index}].kind is unsupported: {step.kind!r}")
        expected_variant = {
            "analysis": AnalysisStep,
            "agent": AgentStep,
            "tool": ToolStep,
            "schedule": ScheduleStep,
            "join": JoinStep,
        }[step.kind]
        if isinstance(step, _TypedStepBase) and type(step) is not expected_variant:
            raise PlanValidationError(
                f"steps[{index}] concrete type does not match kind {step.kind!r}"
            )
        canonical_json_bytes(step.to_dict(), path=f"steps[{index}]")
        if not step.id or step.id in ids:
            raise PlanValidationError(f"steps[{index}].id must be unique and non-empty")
        ids.add(step.id)
        step_map[step.id] = step
        if any(not isinstance(dep, str) or not dep for dep in step.depends_on):
            raise PlanValidationError(f"steps[{index}].depends_on contains an invalid id")
        tool_name = getattr(step, "tool_name", None)
        retry_owner = getattr(step, "retry_owner", None)
        timeout_seconds = getattr(step, "timeout_seconds", None)
        idempotency_key = getattr(step, "idempotency_key", None)
        retry_budget = getattr(step, "retry_budget", 0)
        if step.kind == "tool":
            if tool_name is not None and (
                not isinstance(tool_name, str) or not tool_name.strip()
            ):
                raise PlanValidationError(
                    f"steps[{index}].tool_name must be a non-empty string"
                )
            if not isinstance(getattr(step, "arguments", None), dict):
                raise PlanValidationError(f"steps[{index}].arguments must be an object")
            if type(retry_budget) is not int or retry_budget < 0:
                raise PlanValidationError(
                    f"steps[{index}].retry_budget must be a non-negative integer"
                )
            valid_timeout = (
                (type(timeout_seconds) is int and timeout_seconds > 0)
                or (
                    type(timeout_seconds) is float
                    and math.isfinite(timeout_seconds)
                    and timeout_seconds > 0
                )
            )
            if timeout_seconds is not None and not valid_timeout:
                raise PlanValidationError(
                    f"steps[{index}].timeout_seconds must be a finite positive number"
                )
        if step.kind == "tool" and step.plan_version >= 2:
            if not getattr(step, "tool_name", None):
                raise PlanValidationError(f"steps[{index}].tool_name is required for typed tool steps")
            if timeout_seconds is None:
                raise PlanValidationError(
                    f"steps[{index}].timeout_seconds is required for typed tool steps"
                )
            if not isinstance(retry_owner, str) or not retry_owner.strip():
                raise PlanValidationError(f"steps[{index}].retry_owner is required")
            if retry_owner not in RETRY_OWNERS:
                raise PlanValidationError(f"steps[{index}].retry_owner is unsupported: {retry_owner!r}")
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise PlanValidationError(
                    f"steps[{index}].idempotency_key must be a non-empty string"
                )
            if step.success_criteria is None:
                raise PlanValidationError(f"steps[{index}].success_criteria is required")
        if isinstance(step, AnalysisStep):
            if not isinstance(step.max_input_chars, int) or isinstance(step.max_input_chars, bool) or step.max_input_chars <= 0:
                raise PlanValidationError(f"steps[{index}].max_input_chars must be a positive integer")
            if not isinstance(step.max_output_chars, int) or isinstance(step.max_output_chars, bool) or step.max_output_chars <= 0:
                raise PlanValidationError(f"steps[{index}].max_output_chars must be a positive integer")
            total_analysis_input += step.max_input_chars
            total_analysis_output += step.max_output_chars
        if isinstance(step, AgentStep):
            if step.model is not None and (not isinstance(step.model, str) or not step.model.strip()):
                raise PlanValidationError(f"steps[{index}].model must be a non-empty string")
            if not isinstance(step.max_tokens, int) or isinstance(step.max_tokens, bool) or step.max_tokens <= 0:
                raise PlanValidationError(f"steps[{index}].max_tokens must be a positive integer")
            if not isinstance(step.capability_budget, int) or isinstance(step.capability_budget, bool) or step.capability_budget <= 0:
                raise PlanValidationError(f"steps[{index}].capability_budget must be a positive integer")
            total_agent_tokens += step.max_tokens
            total_agent_capabilities += step.capability_budget
        if isinstance(step, ScheduleStep):
            if step.schedule_mode not in {"once", "interval"}:
                raise PlanValidationError(f"steps[{index}].schedule_mode is unsupported: {step.schedule_mode!r}")
            if not isinstance(step.prompt, str):
                raise PlanValidationError(f"steps[{index}].prompt must be a string")
            if not isinstance(step.run_after_seconds, int) or isinstance(step.run_after_seconds, bool) or step.run_after_seconds < 0:
                raise PlanValidationError(f"steps[{index}].run_after_seconds must be a non-negative integer")
            if not isinstance(step.interval_seconds, int) or isinstance(step.interval_seconds, bool) or step.interval_seconds <= 0:
                raise PlanValidationError(f"steps[{index}].interval_seconds must be a positive integer")
            try:
                if step.timezone != "UTC":
                    ZoneInfo(step.timezone)
            except (TypeError, ZoneInfoNotFoundError) as exc:
                raise PlanValidationError(f"steps[{index}].timezone is invalid: {step.timezone!r}") from exc
            if not isinstance(step.cancellation_key, str) or not step.cancellation_key.strip():
                raise PlanValidationError(f"steps[{index}].cancellation_key is required")
            total_schedule_seconds += (
                step.run_after_seconds if step.schedule_mode == "once" else step.interval_seconds
            )
        if isinstance(step, JoinStep):
            if step.merge_policy not in {"any_success", "all_success"}:
                raise PlanValidationError(f"steps[{index}].merge_policy is unsupported: {step.merge_policy!r}")
            if not isinstance(step.max_merged_chars, int) or isinstance(step.max_merged_chars, bool) or step.max_merged_chars <= 0:
                raise PlanValidationError(f"steps[{index}].max_merged_chars must be a positive integer")
            total_join_chars += step.max_merged_chars
        if step.kind == "tool":
            total_retries += retry_budget
            total_timeout += timeout_seconds or 0
    for step in steps:
        _validate_predicate(
            step.success_criteria,
            path=f"step {step.id}.success_criteria",
            known_step_ids={step.id},
            allow_implicit_source=True,
        )
        for dep in step.depends_on:
            if dep not in step_map and not allow_external_dependencies:
                raise PlanValidationError(f"step {step.id} depends on unknown step {dep}")
        if step.condition is not None:
            if step.condition.mode not in {"continue_if", "skip_if"}:
                raise PlanValidationError(f"step {step.id} has unsupported condition mode")
            predicate = step.condition.to_predicate()
            if predicate is None:
                raise PlanValidationError(f"step {step.id} condition has no predicate")
            _validate_predicate(
                predicate,
                path=f"step {step.id}.condition.predicate",
                known_step_ids=ids,
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id not in step_map:
            return
        if step_id in visiting:
            raise PlanValidationError(f"dependency cycle detected at {step_id}")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in step_map[step_id].depends_on:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in step_map:
        visit(step_id)
    if total_retries > max_retry_budget:
        raise PlanValidationError(f"plan exceeds retry budget ({total_retries} > {max_retry_budget})")
    if total_timeout > max_timeout_seconds:
        raise PlanValidationError(f"plan exceeds timeout budget ({total_timeout} > {max_timeout_seconds})")
    if total_analysis_input > max_analysis_input_chars:
        raise PlanValidationError(
            f"plan exceeds analysis input budget ({total_analysis_input} > {max_analysis_input_chars})"
        )
    if total_analysis_output > max_analysis_output_chars:
        raise PlanValidationError(
            f"plan exceeds analysis output budget ({total_analysis_output} > {max_analysis_output_chars})"
        )
    if total_agent_tokens > max_agent_tokens:
        raise PlanValidationError(f"plan exceeds agent token budget ({total_agent_tokens} > {max_agent_tokens})")
    if total_agent_capabilities > max_agent_capability_budget:
        raise PlanValidationError(
            f"plan exceeds agent capability budget ({total_agent_capabilities} > {max_agent_capability_budget})"
        )
    if total_schedule_seconds > max_schedule_seconds:
        raise PlanValidationError(
            f"plan exceeds schedule bounds budget ({total_schedule_seconds} > {max_schedule_seconds})"
        )
    if total_join_chars > max_join_chars:
        raise PlanValidationError(f"plan exceeds join merge budget ({total_join_chars} > {max_join_chars})")


class Planner:
    """最小启发式 Planner。

    当前不调用第二个 LLM，只将目标封装成一个可扩展的步骤列表。
    后续可以替换为真正的多步规划器。
    """

    def plan(self, goal: str, interpret_result: InterpretResult | None = None) -> PlanResult:
        normalized = (goal or "").strip()
        if not normalized:
            return PlanResult(goal="", steps=[])

        # Ambiguous destructive intent is a planning outcome, never an
        # executable tool prompt. The caller can ask the returned question.
        lowered = normalized.lower()
        destructive = bool(re.search(
            r"\b(?:delete|remove|overwrite)\b.*\b(?:file|folder|directory|data|record|app|application)\b"
            r"|\bwrite\b.*\b(?:file|disk)\b",
            lowered,
        )) or any(token in normalized for token in ("删除文件", "删除目录", "删除数据", "写入文件", "覆盖文件"))
        unsafe_scope = any(token in lowered for token in ("everything", "all files", "entire disk", "delete /")) \
            or any(token in normalized for token in ("删除全部", "所有文件", "整个磁盘"))
        destructive_verb = bool(re.search(r"\b(?:delete|remove|overwrite)\b", lowered)) or any(
            token in normalized for token in ("删除", "覆盖")
        )
        if destructive_verb and unsafe_scope:
            return PlanResult(
                goal=normalized,
                outcome="refused",
                refusal_reason="destructive_scope_cannot_be_made_safe",
            )
        has_target = bool(re.search(r"(?:[A-Za-z]:[\\/]|/[\\w.-]+|https?://\S+|\S+\.(?:txt|json|md|py))", normalized))
        if destructive and not has_target:
            return PlanResult(
                goal=normalized,
                outcome="clarification_required",
                clarification_question="请明确要操作的目标及范围。",
                refusal_reason="destructive_scope_ambiguous",
            )

        delay_match = re.search(r"(\d+)\s*(秒|分钟|分|小时)后", normalized)
        interval_match = re.search(r"每隔\s*(\d+)\s*(秒|分钟|分|小时)", normalized)
        has_immediate_hint = any(token in normalized for token in ["现在", "立刻", "马上", "先"])
        has_tool_hint = (
            bool(interpret_result.tool_hint) if interpret_result is not None else any(
                token in normalized for token in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件", "写入文件"]
            )
        ) or bool(re.search(r"https?://\S+", normalized))

        conditional_match = re.search(r"(.+?)(?:，|,|。|\s)+如果(成功|失败)(?:且([^，,。]*))?(?:的话)?(?:，|,|\s)*(.*)$", normalized)
        if conditional_match:
            primary_prompt = conditional_match.group(1).strip()
            condition_kind = conditional_match.group(2).strip()
            condition_detail = (conditional_match.group(3) or "").strip()
            branch_prompt = conditional_match.group(4).strip()
            condition_filters = self._condition_filters_from_text(condition_detail)

            analysis_step = self._make_step(
                title="Understand conditional goal",
                kind="analysis",
                description=normalized,
            )
            primary_step = self._make_step(
                title="Execute primary branch",
                kind="tool" if self._looks_like_tool_prompt(primary_prompt) else "agent",
                description=primary_prompt,
                payload={"prompt": primary_prompt},
                depends_on=[analysis_step.id],
            )
            else_match = re.search(r"(.+?)(?:，|,|\s)+否则(?:的话)?(?:，|,|\s)*(.*)$", branch_prompt)
            branch_steps: list[PlanStepUnion] = []
            if else_match:
                conditional_prompt = else_match.group(1).strip()
                fallback_prompt = else_match.group(2).strip()
                branch_steps.append(self._make_step(
                    title=f"Execute {'failure' if condition_kind == '失败' else 'success'} branch",
                    kind="tool" if self._looks_like_tool_prompt(conditional_prompt) else "agent",
                    description=conditional_prompt,
                    payload={"prompt": conditional_prompt},
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="continue_if",
                        status_in=["error", "skipped"] if condition_kind == "失败" else ["ok"],
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
                branch_steps.append(self._make_step(
                    title="Execute else branch",
                    kind="tool" if self._looks_like_tool_prompt(fallback_prompt) else "agent",
                    description=fallback_prompt,
                    payload={"prompt": fallback_prompt},
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="skip_if",
                        status_in=["error", "skipped"] if condition_kind == "失败" else ["ok"],
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
            else:
                selected_statuses = ["error", "skipped"] if condition_kind == "失败" else ["ok"]
                branch_steps.append(self._make_step(
                    title=f"Execute {'failure' if condition_kind == '失败' else 'success'} branch",
                    kind="tool" if self._looks_like_tool_prompt(branch_prompt) else "agent",
                    description=branch_prompt,
                    payload={"prompt": branch_prompt},
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="continue_if",
                        status_in=selected_statuses,
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
                branch_steps.append(self._make_step(
                    title="Continue without conditional branch",
                    kind="analysis",
                    description="No one-sided conditional branch was selected; continue to final synthesis.",
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="skip_if",
                        status_in=selected_statuses,
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
            join_step = self._make_step(
                title="Merge conditional branches",
                kind="join",
                description="Merge the branch path that actually ran before final synthesis.",
                depends_on=[step.id for step in branch_steps],
            )
            synthesis_step = self._make_step(
                title="Synthesize conditional result",
                kind="agent",
                description=normalized,
                payload={"prompt": normalized},
                depends_on=[join_step.id],
                condition=StepCondition(
                    source_step_id=join_step.id,
                    mode="continue_if",
                    status_in=["ok"],
                ),
            )

            return PlanResult(
                goal=normalized,
                mode="immediate",
                steps=[analysis_step, primary_step, *branch_steps, join_step, synthesis_step],
                immediate_steps=[primary_step, *branch_steps, join_step, synthesis_step],
            )

        def to_seconds(value: str, unit: str) -> int:
            amount = int(value)
            if unit == "秒":
                return amount
            if unit in {"分钟", "分"}:
                return amount * 60
            if unit == "小时":
                return amount * 3600
            return amount

        if interval_match or (interpret_result is not None and interpret_result.intent == "schedule" and "每隔" in normalized):
            analysis_step = self._make_step(
                title="Interpret scheduled interval request",
                kind="analysis",
                description=normalized,
            )
            interval_seconds = to_seconds(interval_match.group(1), interval_match.group(2)) if interval_match else 60
            scheduled_step = self._make_step(
                title="Create interval schedule",
                kind="schedule",
                description=f"interval={interval_seconds}s",
                payload={"mode": "interval", "interval_seconds": interval_seconds, "prompt": normalized},
                depends_on=[analysis_step.id],
            )
            result = PlanResult(
                goal=normalized,
                mode="scheduled_interval",
                interval_seconds=interval_seconds,
                steps=[
                    analysis_step,
                    scheduled_step,
                ],
                scheduled_steps=[scheduled_step],
            )
            if has_immediate_hint:
                immediate_step = self._make_step(
                    title="Execute immediate request",
                    kind="agent",
                    description=normalized,
                    payload={"prompt": normalized},
                    depends_on=[analysis_step.id],
                )
                result.mode = "mixed"
                result.steps.append(immediate_step)
                result.immediate_steps.append(immediate_step)
            return result

        if delay_match or (interpret_result is not None and interpret_result.intent == "schedule"):
            analysis_step = self._make_step(
                title="Interpret delayed task",
                kind="analysis",
                description=normalized,
            )
            delay_seconds = to_seconds(delay_match.group(1), delay_match.group(2)) if delay_match else 60
            scheduled_step = self._make_step(
                title="Create one-shot schedule",
                kind="schedule",
                description=f"delay={delay_seconds}s",
                payload={"mode": "once", "run_after_seconds": delay_seconds, "prompt": normalized},
                depends_on=[analysis_step.id],
            )
            result = PlanResult(
                goal=normalized,
                mode="scheduled_once",
                delay_seconds=delay_seconds,
                steps=[
                    analysis_step,
                    scheduled_step,
                ],
                scheduled_steps=[scheduled_step],
            )
            if has_immediate_hint:
                immediate_step = self._make_step(
                    title="Execute immediate request",
                    kind="agent",
                    description=normalized,
                    payload={"prompt": normalized},
                    depends_on=[analysis_step.id],
                )
                result.mode = "mixed"
                result.steps.append(immediate_step)
                result.immediate_steps.append(immediate_step)
            return result

        tool_prompts = self._split_tool_prompts(normalized) if has_tool_hint else []
        if len(tool_prompts) > 1:
            analysis_step = self._make_step(
                title="Understand goal",
                kind="analysis",
                description=normalized,
            )
            tool_steps: list[PlanStepUnion] = []
            previous_id = analysis_step.id
            for index, prompt in enumerate(tool_prompts):
                step = self._make_step(
                    title=f"Execute tool step {index + 1}",
                    kind="tool",
                    description=prompt,
                    payload={"prompt": prompt},
                    depends_on=[previous_id],
                )
                tool_steps.append(step)
                previous_id = step.id
            followup_agent_step = self._make_step(
                title="Synthesize final response",
                kind="agent",
                description=normalized,
                payload={"prompt": normalized},
                depends_on=[previous_id],
            )
            return PlanResult(
                goal=normalized,
                mode="immediate",
                steps=[
                    analysis_step,
                    *tool_steps,
                    followup_agent_step,
                ],
                immediate_steps=[*tool_steps, followup_agent_step],
            )

        analysis_step = self._make_step(
            title="Understand goal",
            kind="analysis",
            description=normalized,
        )
        immediate_step = self._make_step(
            title="Execute via agent pipeline",
            kind="tool" if has_tool_hint else "agent",
            description=normalized,
            payload={"prompt": normalized},
            depends_on=[analysis_step.id],
        )
        return PlanResult(
            goal=normalized,
            mode="immediate",
            steps=[
                analysis_step,
                immediate_step,
            ],
            immediate_steps=[immediate_step],
        )

    def _make_step(
        self,
        *,
        title: str,
        kind: str,
        description: str = "",
        payload: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        condition: StepCondition | None = None,
    ) -> PlanStepUnion:
        source_payload = dict(payload or {})
        typed_tool_name: str | None = None
        typed_arguments: dict[str, Any] = {}
        if kind == "tool":
            typed_tool_name = source_payload.get("tool_name")
            if isinstance(source_payload.get("arguments"), dict):
                typed_arguments = dict(source_payload["arguments"])
            # Legacy prompt adapter: emit a typed browser call when the
            # existing fast-path contains a URL; all other prompts remain
            # executable through StepExecutor's compatibility adapter.
            if not typed_tool_name:
                url_match = re.search(r"https?://\S+", str(source_payload.get("prompt") or description))
                if url_match:
                    typed_tool_name = "browser.open_page"
                    typed_arguments = {"url": url_match.group(0).rstrip(".,;，。；")}
            if not typed_tool_name:
                prompt = str(source_payload.get("prompt") or description).strip()
                open_match = re.match(r"(?:open|打开)\s+(.+)$", prompt, re.IGNORECASE)
                read_match = re.search(r"(?:read(?: file)?|读取文件|读文件)\s+(.+)$", prompt, re.IGNORECASE)
                write_match = re.search(r"(?:write(?: file)?|写文件|写入文件)\s+(.+?)(?:\s+(?:content|内容)[:：]?\s*)(.+)$", prompt, re.IGNORECASE)
                if write_match:
                    typed_tool_name = "write_file"
                    typed_arguments = {"path": write_match.group(1).strip(), "content": write_match.group(2).strip()}
                elif read_match:
                    typed_tool_name = "read_file"
                    typed_arguments = {"path": read_match.group(1).strip()}
                elif open_match:
                    typed_tool_name = "open_app"
                    typed_arguments = {"name": open_match.group(1).strip()}
            if typed_tool_name:
                pass
            else:
                # An unrecognized tool-like phrase remains non-executable.
                kind = "agent"

        variant_type: type[PlanStepUnion] | None = {
            "analysis": AnalysisStep,
            "agent": AgentStep,
            "tool": ToolStep,
            "schedule": ScheduleStep,
            "join": JoinStep,
        }.get(kind)
        if variant_type is None:
            raise PlanValidationError(f"unsupported planner step kind: {kind}")
        route = resolve_step_route(kind)
        step_kwargs: dict[str, Any] = {
            "title": title,
            "description": description,
            "depends_on": list(depends_on or []),
            "condition": condition,
            "owner_agent_id": route.owner_agent_id,
            "owner_agent_role": route.owner_agent_role,
            "route_reason": route.route_reason,
        }
        if kind == "tool":
            step_kwargs.update(tool_name=typed_tool_name, arguments=typed_arguments)
        elif kind == "schedule":
            step_kwargs.update(
                schedule_mode=str(source_payload.get("mode") or "once"),
                prompt=str(source_payload.get("prompt") or description),
                run_after_seconds=int(source_payload.get("run_after_seconds") or 0),
                interval_seconds=int(source_payload.get("interval_seconds") or 60),
                timezone=str(source_payload.get("timezone") or "UTC"),
                cancellation_key=source_payload.get("cancellation_key"),
            )
        contract = {
            "variant": variant_type.__name__,
            **step_kwargs,
            "condition": condition.to_dict() if condition is not None else None,
        }
        encoded = canonical_json_bytes(contract, path="planner step contract")
        step_kwargs["id"] = f"step_{hashlib.sha256(encoded).hexdigest()[:16]}"
        return variant_type(**step_kwargs)

    def _looks_like_tool_prompt(self, text: str) -> bool:
        return any(keyword in text for keyword in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件", "写入文件"]) or bool(re.search(r"https?://\S+", text))

    def _condition_filters_from_text(self, text: str) -> dict[str, list[str]]:
        normalized = (text or "").strip()
        if not normalized:
            return {}

        content_match = re.search(r"(?:输出|结果|内容)包含\s*([^，,。]+)", normalized)
        error_match = re.search(r"(?:错误|报错|异常)包含\s*([^，,。]+)", normalized)
        filters: dict[str, list[str]] = {}
        if content_match:
            filters["content_contains"] = [content_match.group(1).strip()]
        if error_match:
            filters["error_contains"] = [error_match.group(1).strip()]
        return filters

    def _split_tool_prompts(self, text: str) -> list[str]:
        if not text:
            return []
        parts = [segment.strip(" ，。；;\n\t") for segment in re.split(r"(?:然后|接着|再|并且|并|;|；)", text) if segment.strip(" ，。；;\n\t")]
        tool_like = [
            part for part in parts
            if any(keyword in part for keyword in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件", "写入文件"]) or re.search(r"https?://\S+", part)
        ]
        return tool_like if len(tool_like) >= 2 else []
