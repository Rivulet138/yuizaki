"""Fail-closed contract for host-mediated mouse and keyboard actions.

The agent can only use opaque action sessions issued by the host.  This module
does not contain a native input implementation; a host adapter must be
explicitly injected before a non-dry-run session can execute an action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import secrets
import threading
import time
from typing import Any, Callable, Literal, Protocol
import weakref

from .permission_receipt import PermissionReceipt
from .tool_registry import ToolDefinition, ToolRegistry
from .tool_registry import _verify_execution_permit
from .tool_result import ToolResultEnvelope


class ComputerUseError(RuntimeError):
    """A deterministic, fail-closed computer-use rejection."""

    def __init__(self, code: str, message: str, *, failure_category: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.failure_category = failure_category


@dataclass(frozen=True)
class ComputerUseScope:
    workspace_id: str
    session_id: str
    turn_id: str
    request_id: str
    generation_id: str
    interruption_epoch: int
    app_id: str
    window_id: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "request_id": self.request_id,
            "generation_id": self.generation_id,
            "interruption_epoch": self.interruption_epoch,
            "app_id": self.app_id,
            "window_id": self.window_id,
        }


@dataclass(frozen=True)
class ComputerUseAction:
    action_type: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.action_type, **self.parameters}


@dataclass(frozen=True)
class ComputerUseAdapterResult:
    category: Literal["completed"] = "completed"
    evidence: dict[str, str] = field(default_factory=dict)


class ComputerUseAdapter(Protocol):
    """Host-owned boundary for native input injection."""

    def execute(
        self,
        *,
        scope: ComputerUseScope,
        action: ComputerUseAction,
        stop_fence: ComputerUseStopFence,
    ) -> ComputerUseAdapterResult: ...


@dataclass(frozen=True)
class ComputerUseStopFence:
    """Host-queryable epoch fence for cooperative input cancellation."""

    issued_epoch: int
    _epoch_provider: Callable[[], int]

    @property
    def stopped(self) -> bool:
        return self._epoch_provider() != self.issued_epoch

    def raise_if_stopped(self) -> None:
        if self.stopped:
            raise ComputerUseError("CU_EMERGENCY_STOPPED", "action was invalidated by emergency stop")


@dataclass
class _ActionSession:
    scope: ComputerUseScope
    dry_run: bool
    expires_at: float
    action_budget: int
    stop_epoch: int
    last_sequence: int = 0
    used_actions: int = 0


_SCOPE_FIELDS = (
    "workspace_id",
    "session_id",
    "turn_id",
    "request_id",
    "generation_id",
    "app_id", "window_id",
)
_BUTTONS = {"left", "middle", "right"}
_KEYS = {
    "alt", "backspace", "ctrl", "delete", "down", "end", "enter", "escape",
    "home", "left", "meta", "pagedown", "pageup", "right", "shift", "space",
    "tab", "up",
    *(f"f{index}" for index in range(1, 13)),
    *(chr(code) for code in range(ord("a"), ord("z") + 1)),
    *(str(index) for index in range(10)),
}


def _opaque(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ComputerUseError("CU_INVALID_SCOPE", f"{field} must be an opaque string")
    clean = value.strip()
    if not clean or len(clean) > 256 or any(ord(char) < 32 for char in clean):
        raise ComputerUseError("CU_INVALID_SCOPE", f"{field} is invalid")
    return clean


def _scope(values: dict[str, Any]) -> ComputerUseScope:
    interruption_epoch = values.get("interruption_epoch")
    if isinstance(interruption_epoch, bool) or not isinstance(interruption_epoch, int) or interruption_epoch < 0:
        raise ComputerUseError("CU_INVALID_SCOPE", "interruption_epoch must be a non-negative integer")
    return ComputerUseScope(
        **{field: _opaque(values.get(field), field) for field in _SCOPE_FIELDS},
        interruption_epoch=interruption_epoch,
    )


def _integer(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ComputerUseError("CU_INVALID_ACTION", f"{field} must be an integer from {minimum} to {maximum}")
    return value


def _exact_keys(action: dict[str, Any], expected: set[str]) -> None:
    if set(action) != expected:
        raise ComputerUseError("CU_INVALID_ACTION", "action contains missing or unsupported parameters")


def parse_action(value: object) -> ComputerUseAction:
    if not isinstance(value, dict):
        raise ComputerUseError("CU_INVALID_ACTION", "action must be an object")
    action_type = value.get("type")
    if action_type == "move":
        _exact_keys(value, {"type", "x", "y"})
        return ComputerUseAction("move", {
            "x": _integer(value.get("x"), "x", minimum=0, maximum=100_000),
            "y": _integer(value.get("y"), "y", minimum=0, maximum=100_000),
        })
    if action_type == "click":
        _exact_keys(value, {"type", "button", "count"})
        button = value.get("button")
        if button not in _BUTTONS:
            raise ComputerUseError("CU_INVALID_ACTION", "button must be left, middle, or right")
        return ComputerUseAction("click", {
            "button": button,
            "count": _integer(value.get("count"), "count", minimum=1, maximum=3),
        })
    if action_type == "key_press":
        _exact_keys(value, {"type", "keys"})
        keys = value.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
            raise ComputerUseError("CU_INVALID_ACTION", "keys must contain one to four supported keys")
        normalized: list[str] = []
        for key in keys:
            if not isinstance(key, str) or key.lower() not in _KEYS:
                raise ComputerUseError("CU_INVALID_ACTION", "keys contains an unsupported key")
            normalized.append(key.lower())
        if len(set(normalized)) != len(normalized):
            raise ComputerUseError("CU_INVALID_ACTION", "keys must not contain duplicates")
        return ComputerUseAction("key_press", {"keys": normalized})
    if action_type == "text_input":
        _exact_keys(value, {"type", "text"})
        text = value.get("text")
        if not isinstance(text, str) or not text or len(text) > 4096 or "\x00" in text:
            raise ComputerUseError("CU_INVALID_ACTION", "text must contain 1 to 4096 characters without NUL")
        return ComputerUseAction("text_input", {"text": text})
    raise ComputerUseError("CU_INVALID_ACTION", "action type is not supported")


class ComputerUseController:
    """Host-issued action sessions with replay, budget, TTL, and stop fencing."""

    def __init__(
        self,
        *,
        adapter: ComputerUseAdapter | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self._clock = clock
        self._sessions: dict[str, _ActionSession] = {}
        self._context_bindings: dict[int, tuple[weakref.ReferenceType[Any], str, ComputerUseScope]] = {}
        self._used_execution_permits: set[str] = set()
        self._stop_epoch = 0
        self._lock = threading.Lock()

    @property
    def stop_epoch(self) -> int:
        with self._lock:
            return self._stop_epoch

    def issue_session(
        self,
        *,
        scope: ComputerUseScope,
        dry_run: bool = True,
        ttl_seconds: float = 60.0,
        action_budget: int = 20,
    ) -> str:
        validated_scope = _scope(scope.to_dict())
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not 0 < ttl_seconds <= 600:
            raise ComputerUseError("CU_INVALID_SESSION", "ttl_seconds must be greater than 0 and at most 600")
        if isinstance(action_budget, bool) or not isinstance(action_budget, int) or not 1 <= action_budget <= 100:
            raise ComputerUseError("CU_INVALID_SESSION", "action_budget must be from 1 to 100")
        if not isinstance(dry_run, bool):
            raise ComputerUseError("CU_INVALID_SESSION", "dry_run must be a boolean")
        action_session_id = f"cu_{secrets.token_urlsafe(24)}"
        with self._lock:
            self._sessions[action_session_id] = _ActionSession(
                scope=validated_scope,
                dry_run=dry_run,
                expires_at=self._clock() + float(ttl_seconds),
                action_budget=action_budget,
                stop_epoch=0,
            )
        return action_session_id

    def emergency_stop(self, *, workspace_id: str | None = None, session_id: str | None = None) -> int:
        """Fence matching action sessions and advance the host-visible revision."""
        with self._lock:
            self._stop_epoch += 1
            for session in self._sessions.values():
                if workspace_id is not None and session.scope.workspace_id != workspace_id:
                    continue
                if session_id is not None and session.scope.session_id != session_id:
                    continue
                session.stop_epoch += 1
            return self._stop_epoch

    def _session_stop_epoch(self, action_session_id: str) -> int:
        with self._lock:
            session = self._sessions.get(action_session_id)
            return session.stop_epoch if session is not None else -1

    def bind_context(self, ctx: Any, *, action_session_id: str, trusted_scope: ComputerUseScope) -> None:
        """Bind a host context identity without exposing the session through ctx."""
        session_key = _opaque(action_session_id, "action_session_id")
        validated_scope = _scope(trusted_scope.to_dict())
        context_id = id(ctx)

        def remove(reference: weakref.ReferenceType[Any]) -> None:
            with self._lock:
                existing = self._context_bindings.get(context_id)
                if existing is not None and existing[0] is reference:
                    self._context_bindings.pop(context_id, None)

        try:
            reference = weakref.ref(ctx, remove)
        except TypeError as exc:
            raise ComputerUseError("CU_INVALID_CONTEXT", "host context must support weak references") from exc
        with self._lock:
            session = self._sessions.get(session_key)
            if session is None or session.scope != validated_scope:
                raise ComputerUseError("CU_SCOPE_MISMATCH", "host binding does not match the action session")
            self._context_bindings[context_id] = (reference, session_key, validated_scope)

    def _binding_for_context(self, ctx: Any) -> tuple[str, ComputerUseScope]:
        with self._lock:
            binding = self._context_bindings.get(id(ctx))
            if binding is None or binding[0]() is not ctx:
                raise ComputerUseError("CU_HOST_BINDING_MISSING", "host computer-use binding is unavailable")
            return binding[1], binding[2]

    def _permit_claims(self, ctx: Any) -> str:
        session_key, trusted_scope = self._binding_for_context(ctx)
        material = json.dumps(
            {"action_session_id": session_key, "scope": trusted_scope.to_dict()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def invoke(
        self,
        *,
        action_session_id: object,
        scope_values: dict[str, Any],
        sequence: object,
        action_value: object,
        preview_only: bool,
        permission_receipt: PermissionReceipt | None = None,
        tool_args: dict[str, Any] | None = None,
        trusted_context: Any = None,
        execution_permit: object = None,
    ) -> dict[str, Any]:
        session_key = _opaque(action_session_id, "action_session_id")
        requested_scope = _scope(scope_values)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ComputerUseError("CU_INVALID_SEQUENCE", "sequence must be a positive integer")
        action = parse_action(action_value)
        verified_permit_nonce = None
        if trusted_context is not None:
            verified_permit_nonce = _verify_execution_permit(
                execution_permit,
                tool_name="computer.perform_action",
                parameters=tool_args or {},
                ctx=trusted_context,
                receipt=permission_receipt,
                claims=self._permit_claims(trusted_context),
            )

        with self._lock:
            session = self._sessions.get(session_key)
            if session is None:
                raise ComputerUseError("CU_SESSION_NOT_FOUND", "action session is unknown")
            if session.stop_epoch > 0:
                raise ComputerUseError("CU_EMERGENCY_STOPPED", "action session was invalidated by emergency stop")
            if self._clock() >= session.expires_at:
                raise ComputerUseError("CU_SESSION_EXPIRED", "action session has expired")
            if requested_scope != session.scope:
                raise ComputerUseError("CU_SCOPE_MISMATCH", "action scope does not match the host-issued session")
            dry_run = preview_only or session.dry_run
            if not dry_run:
                if (
                    permission_receipt is None
                    or permission_receipt.decision != "allowed"
                    or permission_receipt.reason_code != "user_allowed"
                    or permission_receipt.decided_at is None
                    or permission_receipt.capability_id != "computer.perform_action"
                    or permission_receipt.parameters != (tool_args or {})
                ):
                    raise ComputerUseError("CU_CONFIRMATION_REQUIRED", "a fresh matching user confirmation is required")
                if verified_permit_nonce is None:
                    raise ComputerUseError("CU_CONFIRMATION_REQUIRED", "a verified execution permit is required")
                if verified_permit_nonce in self._used_execution_permits:
                    raise ComputerUseError("CU_PERMISSION_REPLAY", "the execution permission was already consumed")
            expected_sequence = session.last_sequence + 1
            if sequence != expected_sequence:
                raise ComputerUseError("CU_SEQUENCE_MISMATCH", f"expected sequence {expected_sequence}")
            if session.used_actions >= session.action_budget:
                raise ComputerUseError("CU_ACTION_BUDGET_EXHAUSTED", "action session budget is exhausted")

            # Consume before crossing the host boundary.  An adapter error may
            # have an uncertain side effect and therefore must never be replayed.
            session.last_sequence = sequence
            session.used_actions += 1
            remaining = session.action_budget - session.used_actions
            if not dry_run and permission_receipt is not None:
                self._used_execution_permits.add(verified_permit_nonce or "")
            evidence = {
                "scope": session.scope.to_dict(),
                "sequence": sequence,
                "action": action.to_dict(),
                "dry_run": dry_run,
                "executed": False,
                "remaining_budget": remaining,
                "stop_epoch": session.stop_epoch,
            }
            if dry_run:
                return {"code": "CU_PREVIEW" if preview_only else "CU_DRY_RUN", "evidence": evidence}
            adapter = self.adapter
            if adapter is None:
                raise ComputerUseError("CU_ADAPTER_UNAVAILABLE", "no host computer-use adapter is configured")
            fence = ComputerUseStopFence(
                session.stop_epoch,
                lambda: self._session_stop_epoch(session_key),
            )

        # Native host work must never hold the controller lock: emergency_stop
        # remains immediate even if the adapter blocks.  Cooperative adapters
        # check the fence directly before each native input operation.
        try:
            fence.raise_if_stopped()
            adapter_result = adapter.execute(scope=requested_scope, action=action, stop_fence=fence)
            fence.raise_if_stopped()
            if not isinstance(adapter_result, ComputerUseAdapterResult):
                raise TypeError("adapter must return ComputerUseAdapterResult")
            if len(adapter_result.evidence) > 8 or any(
                not isinstance(key, str) or not isinstance(value, str) or len(key) > 64 or len(value) > 256
                for key, value in adapter_result.evidence.items()
            ):
                raise TypeError("adapter evidence exceeds its bounded string contract")
        except ComputerUseError:
            raise
        except Exception as exc:
            category = "invalid_result" if isinstance(exc, TypeError) else "adapter_error"
            raise ComputerUseError(
                "CU_ADAPTER_FAILURE",
                f"host adapter rejected the action: {exc}",
                failure_category=category,
            ) from exc
        evidence["executed"] = True
        evidence["completion"] = {
            "category": adapter_result.category,
            "stop_epoch": fence.issued_epoch,
            "adapter_evidence": dict(adapter_result.evidence),
        }
        return {"code": "CU_EXECUTED", "evidence": evidence}


_ACTION_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"type": {"const": "move"}, "x": {"type": "integer", "minimum": 0, "maximum": 100000}, "y": {"type": "integer", "minimum": 0, "maximum": 100000}},
            "required": ["type", "x", "y"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"type": {"const": "click"}, "button": {"enum": sorted(_BUTTONS)}, "count": {"type": "integer", "minimum": 1, "maximum": 3}},
            "required": ["type", "button", "count"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"type": {"const": "key_press"}, "keys": {"type": "array", "items": {"type": "string", "enum": sorted(_KEYS)}, "minItems": 1, "maxItems": 4, "uniqueItems": True}},
            "required": ["type", "keys"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"type": {"const": "text_input"}, "text": {"type": "string", "minLength": 1, "maxLength": 4096}},
            "required": ["type", "text"],
            "additionalProperties": False,
        },
    ]
}


def _parameters_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "sequence": {"type": "integer", "minimum": 1},
        "action": _ACTION_SCHEMA,
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["sequence", "action"],
        "additionalProperties": False,
    }


def _handler(
    controller: ComputerUseController,
    tool_name: str,
    preview_only: bool,
    args: dict[str, Any],
    ctx: Any,
    permission_receipt: PermissionReceipt | None,
    execution_permit: object,
) -> ToolResultEnvelope:
    try:
        action_session_id, trusted_scope = controller._binding_for_context(ctx)
        result = controller.invoke(
            action_session_id=action_session_id,
            scope_values=trusted_scope.to_dict(),
            sequence=args.get("sequence"),
            action_value=args.get("action"),
            preview_only=preview_only,
            permission_receipt=permission_receipt,
            tool_args=args,
            trusted_context=ctx,
            execution_permit=execution_permit,
        )
        content = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return ToolResultEnvelope(success=True, content=content, source="builtin", tool_name=tool_name, data=result)
    except ComputerUseError as exc:
        data = {"code": exc.code}
        if exc.failure_category is not None:
            data["failure_category"] = exc.failure_category
        return ToolResultEnvelope(success=False, content="", source="builtin", tool_name=tool_name, data=data, error=f"{exc.code}: {exc}")


def register_computer_use_tools(
    registry: ToolRegistry,
    *,
    controller: ComputerUseController | None = None,
    adapter: ComputerUseAdapter | None = None,
) -> ComputerUseController:
    """Register preview and confirmed action capabilities."""
    resolved = controller or ComputerUseController(adapter=adapter)
    registry.register(ToolDefinition(
        name="computer.preview_action",
        description="Validate and preview one scoped mouse or keyboard action without native input.",
        source="builtin",
        parameters=_parameters_schema(),
        handler=lambda args: _handler(resolved, "computer.preview_action", True, args, None, None, None),
        context_handler=lambda args, ctx, receipt, permit: _handler(resolved, "computer.preview_action", True, args, ctx, receipt, permit),
        effect_kind="read",
        risk_level="safe",
        tags=["computer-use", "mouse", "keyboard", "preview", "dry-run"],
        scopes=["computer:preview"],
    ))
    registry.register(ToolDefinition(
        name="computer.perform_action",
        description="Execute one host-authorized scoped mouse or keyboard action.",
        source="builtin",
        parameters=_parameters_schema(),
        handler=lambda args: _handler(resolved, "computer.perform_action", False, args, None, None, None),
        context_handler=lambda args, ctx, receipt, permit: _handler(resolved, "computer.perform_action", False, args, ctx, receipt, permit),
        effect_kind="write",
        execution_permit_claims=lambda _args, ctx: resolved._permit_claims(ctx),
        require_confirm=True,
        risk_level="high",
        tags=["computer-use", "mouse", "keyboard", "input", "side-effect"],
        scopes=["computer:input"],
        allow_remembered_decision=False,
    ))
    return resolved
