from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, ClassVar, Literal

from .context import AgentPipelineResult, AgentRequestContext, TerminalTurnOutcome
from .perception import (
    PerceptionEvidence,
    PerceptionProviderRegistry,
    PerceptionRequest,
)

TurnTrigger = Literal["http", "socket", "voice", "scheduler", "heartbeat"]
VALID_TURN_TRIGGERS = frozenset({"http", "socket", "voice", "scheduler", "heartbeat"})

TurnRunner = Callable[[AgentRequestContext], AgentPipelineResult | Awaitable[AgentPipelineResult]]
TurnStreamingRunner = Callable[
    [AgentRequestContext, Any, Any],
    AgentPipelineResult | Awaitable[AgentPipelineResult],
]
TurnFinalizer = Callable[
    [AgentRequestContext, AgentPipelineResult],
    AgentPipelineResult | Awaitable[AgentPipelineResult],
]
TurnPersister = Callable[["TurnCommit"], Any | Awaitable[Any]]
TurnLoader = Callable[[str], Mapping[str, Any] | None | Awaitable[Mapping[str, Any] | None]]
TurnClaimer = Callable[[str, str, str, float], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
TurnClaimRenewer = Callable[[str, str, int, float], bool | Awaitable[bool]]
TurnClaimReleaser = Callable[[str, str, int], bool | Awaitable[bool]]
TurnDispatcher = Callable[["TurnCommit"], Any | Awaitable[Any]]
TurnReplayDeliverer = Callable[
    [AgentRequestContext, AgentPipelineResult],
    Any | Awaitable[Any],
]
TurnContextBinder = Callable[
    [AgentRequestContext],
    AgentRequestContext | Awaitable[AgentRequestContext],
]
_TURN_SERVICE_PERCEPTION_GRANT = object()


def is_turn_service_perception_request(request: PerceptionRequest) -> bool:
    return request.metadata.get("_turn_service_grant") is _TURN_SERVICE_PERCEPTION_GRANT


@dataclass(frozen=True)
class SemanticTurnRequest:
    """Transport-neutral input shared by every semantic turn entry point."""

    session_id: str
    messages: tuple[dict[str, Any], ...] | list[dict[str, Any]]
    request_id: str | None = None
    workspace_id: str | None = None
    sid: str | None = None
    turn_id: str | None = None
    generation_id: str | None = None
    interruption_epoch: int = 0
    context_options: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SemanticTurnRequest:
        messages = value.get("messages")
        if not isinstance(messages, (list, tuple)):
            raise TypeError("semantic turn messages must be a list or tuple")
        return cls(
            session_id=str(value.get("session_id") or value.get("sessionId") or "").strip(),
            messages=tuple(deepcopy(item) for item in messages if isinstance(item, dict)),
            request_id=_optional_text(value.get("request_id") or value.get("requestId")),
            workspace_id=_optional_text(value.get("workspace_id") or value.get("workspaceId")),
            sid=_optional_text(value.get("sid")),
            turn_id=_optional_text(value.get("turn_id") or value.get("turnId")),
            generation_id=_optional_text(value.get("generation_id") or value.get("generationId")),
            interruption_epoch=max(0, int(value.get("interruption_epoch") or value.get("interruptionEpoch") or 0)),
            context_options=dict(value.get("context_options") or value.get("contextOptions") or {}),
            extra=dict(value.get("extra") or {}),
        )


@dataclass
class TurnCommit:
    """One finalized semantic result and its single persistence outcome."""

    idempotency_key: str
    semantic_fingerprint: str
    trigger: TurnTrigger
    context: AgentRequestContext
    result: AgentPipelineResult
    persisted: bool = False
    persistence_result: Any = None
    claim_owner: str | None = None
    claim_fencing_token: int | None = None
    replayed: bool = False
    outcome: TerminalTurnOutcome = "completed"
    retryable: bool = False
    configured_budget: dict[str, Any] = field(default_factory=dict)
    consumed_usage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outcome = self.result.outcome
        self.retryable = self.result.retryable
        self.configured_budget = deepcopy(self.result.configured_budget)
        self.consumed_usage = deepcopy(self.result.consumed_usage)


class TurnIdentityConflictError(RuntimeError):
    """Raised when one turn identity is reused with different semantic input."""


class TurnClaimLostError(RuntimeError):
    """Raised when an executor loses its durable claim before commit."""


@dataclass(frozen=True)
class TurnPorts:
    """Ports owned by the service boundary, independent of HTTP or Socket.IO."""

    run: TurnRunner
    run_streaming: TurnStreamingRunner | None = None
    finalize: TurnFinalizer | None = None
    persist: TurnPersister | None = None
    load: TurnLoader | None = None
    claim: TurnClaimer | None = None
    renew_claim: TurnClaimRenewer | None = None
    release_claim: TurnClaimReleaser | None = None
    dispatch: TurnDispatcher | None = None
    bind_context: TurnContextBinder | None = None

    @classmethod
    def from_pipeline(
        cls,
        pipeline: Any,
        *,
        persist: TurnPersister | None = None,
        load: TurnLoader | None = None,
        claim: TurnClaimer | None = None,
        renew_claim: TurnClaimRenewer | None = None,
        release_claim: TurnClaimReleaser | None = None,
        dispatch: TurnDispatcher | None = None,
        bind_context: TurnContextBinder | None = None,
    ) -> TurnPorts:
        # AgentPipeline.run already returns its finalized result, so wiring it
        # through this adapter must not invoke finalize_result a second time.
        return cls(
            run=pipeline.run,
            run_streaming=getattr(pipeline, "run_streaming", None),
            persist=persist,
            load=load,
            claim=claim,
            renew_claim=renew_claim,
            release_claim=release_claim,
            dispatch=dispatch,
            bind_context=bind_context,
        )


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _await_durable(value: Any) -> tuple[Any, bool]:
    """Finish a durable write even when the caller cancellation races it."""
    if not inspect.isawaitable(value):
        return value, False
    task = asyncio.ensure_future(value)
    cancelled = False
    try:
        return await asyncio.shield(task), False
    except asyncio.CancelledError:
        cancelled = True
        outcome = await asyncio.gather(task, return_exceptions=True)
        result = outcome[0]
        if isinstance(result, BaseException):
            raise result
        return result, cancelled


def _strict_json_value(value: Any, *, path: str = "$") -> Any:
    """Return a JSON-shaped value or reject ambiguous fingerprint input."""

    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"semantic execution input must contain finite JSON numbers at {path}")
        return value
    if isinstance(value, list):
        return [
            _strict_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"semantic execution input requires string keys at {path}")
            normalized[key] = _strict_json_value(item, path=f"{path}.{key}")
        return normalized
    raise TypeError(
        f"semantic execution input must be JSON-serializable at {path}; "
        f"got {type(value).__name__}"
    )


class TurnService:
    """Normalize, execute, finalize, and commit one semantic turn exactly once."""

    _CONTEXT_OPTION_FIELDS = frozenset({
        "temperature", "top_p", "top_k", "min_p", "frequency_penalty",
        "presence_penalty", "repetition_penalty", "max_tokens", "model",
        "reasoning_effort", "thinking_mode", "response_mode", "mcp_enabled",
        "web_search_enabled", "prompt_profile", "pet_control_context", "llm_client",
        "generation_mgr", "tool_registry", "tool_executor", "step_executor",
        "scheduler", "trace_store", "plugin_manager", "permission_request_cb",
        "permission_scope", "autonomy_mode",
    })
    _RUNTIME_CONTEXT_OPTION_FIELDS = frozenset({
        "llm_client", "generation_mgr", "tool_registry", "tool_executor",
        "step_executor", "scheduler", "trace_store", "plugin_manager",
        "permission_request_cb",
    })
    # Caller- or binder-provided extension values that alter planning, prompt
    # assembly, model routing, tool selection, or execution limits. Everything
    # else in ``extra`` is runtime plumbing and must not destabilize replay.
    _SEMANTIC_EXTRA_FIELDS = frozenset({
        "additional_prompt_blocks",
        "allowed_mcp_server_names",
        "allowed_tool_names",
        "configured_budget",
        "execution_mode",
        "force_tool_loop",
        "max_iterations",
        "max_retries",
        "max_tool_calls",
        "memory_sources",
        "model_provider",
        "preferred_tool_names",
        "prefetched_tool_candidates",
        "provider",
        "provider_name",
        "recent_signal_docs",
        "relationship_history",
        "relationship_summary",
        "retrieved_chunks",
        "retry_budget",
        "retry_limit",
        "route",
        "routing_mode",
        "runtime_revision",
        "streaming_tool_max_iterations",
        "system_prompt",
        "system_prompt_modifier",
        "tool_budget",
        "workspace_mcp_preset",
        "workspace_tool_preset",
    })
    _PROJECTION_EXTRA_FIELDS = frozenset({
        "acceptance_id",
        "conversation_id",
        "goal_id",
        "heartbeat_opportunity_id",
        "invocation_source",
        "job_id",
        "operation_id",
        "opportunity_id",
        "owner_agent_id",
        "owner_agent_role",
        "route_reason",
        "run_id",
        "source",
        "source_id",
        "source_kind",
        "task_id",
        "task_mode",
        "task_name",
    })
    _PROJECTION_NESTED_FIELDS: ClassVar[dict[str, frozenset[str]]] = {
        "heartbeat_opportunity": frozenset({
            "goal_id",
            "job_id",
            "opportunity_id",
            "request_id",
            "session_id",
            "source_id",
            "source_kind",
            "workspace_id",
        }),
        "job_outcome": frozenset({
            "conversation_id",
            "job_id",
            "operation_id",
            "owner_agent_id",
            "owner_agent_role",
            "route_reason",
            "run_id",
            "status",
            "task_id",
            "task_mode",
            "task_name",
        }),
        "job_terminal": frozenset({
            "conversation_id",
            "job_id",
            "operation_id",
            "owner_agent_id",
            "owner_agent_role",
            "route_reason",
            "run_id",
            "status",
            "task_id",
            "task_mode",
            "task_name",
        }),
    }

    def __init__(
        self,
        ports: TurnPorts,
        *,
        perception_registry: PerceptionProviderRegistry | None = None,
        retained_commits: int = 256,
        claim_lease_seconds: float = 30.0,
        claim_wait_seconds: float = 30.0,
    ) -> None:
        self.ports = ports
        self.perception_registry = perception_registry
        self.retained_commits = max(1, int(retained_commits))
        self.claim_lease_seconds = max(0.1, float(claim_lease_seconds))
        self.claim_wait_seconds = max(0.1, float(claim_wait_seconds))
        self._commits: OrderedDict[str, TurnCommit] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[TurnCommit]] = {}
        self._inflight_fingerprints: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_pipeline(
        cls,
        pipeline: Any,
        *,
        persist: TurnPersister | None = None,
        load: TurnLoader | None = None,
        claim: TurnClaimer | None = None,
        renew_claim: TurnClaimRenewer | None = None,
        release_claim: TurnClaimReleaser | None = None,
        dispatch: TurnDispatcher | None = None,
        bind_context: TurnContextBinder | None = None,
        perception_registry: PerceptionProviderRegistry | None = None,
        retained_commits: int = 256,
        claim_lease_seconds: float = 30.0,
        claim_wait_seconds: float = 30.0,
    ) -> TurnService:
        """Factory used at an application runtime boundary for one pipeline."""
        return cls(
            TurnPorts.from_pipeline(
                pipeline,
                persist=persist,
                load=load,
                claim=claim,
                renew_claim=renew_claim,
                release_claim=release_claim,
                dispatch=dispatch,
                bind_context=bind_context,
            ),
            perception_registry=perception_registry,
            retained_commits=retained_commits,
            claim_lease_seconds=claim_lease_seconds,
            claim_wait_seconds=claim_wait_seconds,
        )

    async def _collect_perception(
        self,
        ctx: AgentRequestContext,
        *,
        provider_name: str,
        capability: str,
        metadata: Mapping[str, Any] | None = None,
        max_payload_bytes: int | None = None,
        cancellation_signal: Any | None = None,
        consent: object | None = None,
        selection_authority: object | None = None,
    ) -> PerceptionEvidence:
        """Collect evidence bound to this service's immutable semantic turn identity."""
        registry = self.perception_registry
        if registry is None:
            raise RuntimeError("perception provider registry is unavailable")
        workspace_id = str(ctx.workspace_id or "").strip()
        session_id = str(ctx.session_id or "").strip()
        request_id = str(ctx.request_id or "").strip()
        # Direct perception helpers retain compatibility for contexts built by
        # older host call sites. Desktop action authority does not use this
        # extension data; its production binder consumes explicit fields only.
        turn_id = str(ctx.turn_id or ctx.extra.get("turn_id") or "").strip()
        generation_id = str(ctx.generation_id or ctx.extra.get("generation_id") or "").strip()
        if not all((workspace_id, session_id, request_id, turn_id, generation_id)):
            raise ValueError("perception requires a fully scoped semantic turn")
        return await registry.collect(
            provider_name,
            PerceptionRequest(
                workspace_id=workspace_id,
                session_id=session_id,
                turn_id=turn_id,
                request_id=request_id,
                generation_id=generation_id,
                interruption_epoch=max(0, int(ctx.interruption_epoch or ctx.extra.get("interruption_epoch", 0) or 0)),
                capability=capability,
                metadata=dict(metadata or {}),
                max_payload_bytes=max_payload_bytes,
                cancellation_signal=cancellation_signal,
                consent=consent,
                selection_authority=selection_authority,
            ),
        )

    async def collect_socket_screenshot(
        self,
        ctx: AgentRequestContext,
        *,
        consent: object,
        cancellation_signal: Any | None = None,
    ) -> PerceptionEvidence:
        return await self._collect_perception(
            ctx,
            provider_name="desktop-screenshot",
            capability="screenshot",
            metadata={"sid": ctx.sid, "_turn_service_grant": _TURN_SERVICE_PERCEPTION_GRANT},
            cancellation_signal=cancellation_signal,
            consent=consent,
        )

    async def perceive_screenshot(self, ctx: AgentRequestContext, *, consent: object, cancellation_signal: Any | None = None) -> PerceptionEvidence:
        return await self._collect_desktop(ctx, "screenshot", consent, cancellation_signal)

    async def perceive_target_window(self, ctx: AgentRequestContext, *, consent: object, cancellation_signal: Any | None = None) -> PerceptionEvidence:
        return await self._collect_desktop(ctx, "target_window", consent, cancellation_signal)

    async def perceive_active_application(self, ctx: AgentRequestContext, *, consent: object, cancellation_signal: Any | None = None) -> PerceptionEvidence:
        return await self._collect_desktop(ctx, "active_application", consent, cancellation_signal)

    async def perceive_selected_file(self, ctx: AgentRequestContext, *, consent: object, cancellation_signal: Any | None = None) -> PerceptionEvidence:
        return await self._collect_desktop(ctx, "selected_file", consent, cancellation_signal)

    async def perceive_clipboard(self, ctx: AgentRequestContext, *, consent: object, cancellation_signal: Any | None = None) -> PerceptionEvidence:
        return await self._collect_desktop(ctx, "clipboard", consent, cancellation_signal)

    async def perceive_ocr(
        self,
        ctx: AgentRequestContext,
        *,
        consent: object,
        source_evidence: PerceptionEvidence,
        cancellation_signal: Any | None = None,
    ) -> PerceptionEvidence:
        return await self._collect_perception(
            ctx,
            provider_name="desktop-ocr",
            capability="ocr",
            metadata={
                "sid": ctx.sid,
                "_turn_service_grant": _TURN_SERVICE_PERCEPTION_GRANT,
                "source_evidence": source_evidence,
            },
            cancellation_signal=cancellation_signal,
            consent=consent,
        )

    async def _collect_desktop(
        self,
        ctx: AgentRequestContext,
        capability: Literal[
            "screenshot", "target_window", "active_application", "selected_file", "clipboard",
        ],
        consent: object,
        cancellation_signal: Any | None,
    ) -> PerceptionEvidence:
        return await self._collect_perception(
            ctx,
            provider_name=f"electron-{capability}",
            capability=capability,
            metadata={"sid": ctx.sid, "_turn_service_grant": _TURN_SERVICE_PERCEPTION_GRANT},
            cancellation_signal=cancellation_signal,
            consent=consent,
            selection_authority=consent if capability in {"target_window", "selected_file"} else None,
        )

    @staticmethod
    def _coerce_request(request: SemanticTurnRequest | Mapping[str, Any]) -> SemanticTurnRequest:
        return request if isinstance(request, SemanticTurnRequest) else SemanticTurnRequest.from_mapping(request)

    def request_from_context(
        self,
        ctx: AgentRequestContext,
        *,
        trigger: TurnTrigger | str | None = None,
    ) -> SemanticTurnRequest:
        """Project an already-built transport context without dropping runtime ports."""
        if not isinstance(ctx, AgentRequestContext):
            raise TypeError("request_from_context expects AgentRequestContext")
        resolved_trigger = self._trigger(trigger or str(ctx.extra.get("turn_trigger") or "http"))
        options = {
            name: getattr(ctx, name)
            for name in self._CONTEXT_OPTION_FIELDS
            if hasattr(ctx, name)
        }
        extra = dict(ctx.extra)
        extra["turn_trigger"] = resolved_trigger
        return SemanticTurnRequest(
            session_id=ctx.session_id,
            messages=deepcopy(ctx.messages),
            request_id=ctx.request_id,
            workspace_id=ctx.workspace_id,
            sid=ctx.sid,
            turn_id=_optional_text(ctx.turn_id) or _optional_text(ctx.extra.get("turn_id")) or f"turn:{ctx.request_id or ctx.session_id}",
            generation_id=_optional_text(ctx.generation_id) or _optional_text(ctx.extra.get("generation_id")),
            interruption_epoch=max(0, int(ctx.interruption_epoch or ctx.extra.get("interruption_epoch", 0) or 0)),
            context_options=options,
            extra=extra,
        )

    @staticmethod
    def _trigger(value: str) -> TurnTrigger:
        trigger = str(value or "").strip().lower()
        if trigger not in VALID_TURN_TRIGGERS:
            raise ValueError(f"unsupported turn trigger: {trigger or '<empty>'}")
        return trigger  # type: ignore[return-value]

    def build_context(
        self,
        trigger: TurnTrigger | str,
        request: SemanticTurnRequest | Mapping[str, Any],
    ) -> AgentRequestContext:
        normalized_trigger = self._trigger(trigger)
        semantic = self._coerce_request(request)
        session_id = semantic.session_id.strip()
        if not session_id:
            raise ValueError("semantic turn session_id is required")
        request_id = semantic.request_id or f"turn_{uuid.uuid4().hex[:16]}"
        turn_id = semantic.turn_id or f"turn:{request_id}"
        generation_id = semantic.generation_id or f"generation:{turn_id}"
        options = {
            key: value if key in self._RUNTIME_CONTEXT_OPTION_FIELDS else deepcopy(value)
            for key, value in semantic.context_options.items()
            if key in self._CONTEXT_OPTION_FIELDS
        }
        unknown_options = sorted(set(semantic.context_options) - self._CONTEXT_OPTION_FIELDS)
        if unknown_options:
            raise ValueError(f"unsupported semantic turn context options: {', '.join(unknown_options)}")
        # ``extra`` is the established runtime extension point and may hold
        # repositories, cancellation signals, locks, or callbacks. Preserve
        # those references while copying only the container itself.
        extra = dict(semantic.extra)
        extra.update({
            "turn_trigger": normalized_trigger,
            "turn_id": turn_id,
            "generation_id": generation_id,
            "interruption_epoch": max(0, int(semantic.interruption_epoch)),
        })
        return AgentRequestContext(
            sid=semantic.sid or normalized_trigger,
            session_id=session_id,
            request_id=request_id,
            turn_id=turn_id,
            generation_id=generation_id,
            interruption_epoch=max(0, int(semantic.interruption_epoch)),
            messages=[deepcopy(item) for item in semantic.messages],
            workspace_id=semantic.workspace_id,
            extra=extra,
            **options,
        )

    @classmethod
    def semantic_projection_identity(cls, ctx: AgentRequestContext) -> dict[str, Any]:
        projection: dict[str, Any] = {
            "trigger": str(ctx.extra.get("turn_trigger") or "").strip().lower(),
            "flat": {
                name: ctx.extra[name]
                for name in sorted(cls._PROJECTION_EXTRA_FIELDS)
                if name in ctx.extra
            },
            "nested": {},
        }
        nested = projection["nested"]
        if not isinstance(nested, dict):
            raise TypeError("semantic projection identity nested payload must be an object")
        for container_name, fields in sorted(cls._PROJECTION_NESTED_FIELDS.items()):
            candidate = ctx.extra.get(container_name)
            if candidate is None:
                continue
            if not isinstance(candidate, Mapping):
                raise TypeError(
                    f"semantic projection identity {container_name} must be an object"
                )
            nested[container_name] = {
                name: candidate[name]
                for name in sorted(fields)
                if name in candidate
            }
        normalized = _strict_json_value(projection)
        if not isinstance(normalized, dict):
            raise TypeError("semantic projection identity must be a JSON object")
        return normalized

    @classmethod
    def semantic_execution_input(cls, ctx: AgentRequestContext) -> dict[str, Any]:
        canonical = {
            "workspace_id": ctx.workspace_id,
            "session_id": ctx.session_id,
            "request_id": ctx.request_id,
            "turn_id": ctx.turn_id,
            "generation_id": ctx.generation_id,
            "interruption_epoch": ctx.interruption_epoch,
            "messages": ctx.messages,
            "autonomy_mode": ctx.autonomy_mode,
            "model": ctx.model,
            "reasoning_effort": ctx.reasoning_effort,
            "thinking_mode": ctx.thinking_mode,
            "response_mode": ctx.response_mode,
            "temperature": ctx.temperature,
            "top_p": ctx.top_p,
            "top_k": ctx.top_k,
            "min_p": ctx.min_p,
            "frequency_penalty": ctx.frequency_penalty,
            "presence_penalty": ctx.presence_penalty,
            "repetition_penalty": ctx.repetition_penalty,
            "max_tokens": ctx.max_tokens,
            "mcp_enabled": ctx.mcp_enabled,
            "web_search_enabled": ctx.web_search_enabled,
            "prompt_profile": ctx.prompt_profile,
            "pet_control_context": ctx.pet_control_context,
            "permission_scope": ctx.permission_scope,
            "execution_extra": {
                name: ctx.extra[name]
                for name in sorted(cls._SEMANTIC_EXTRA_FIELDS)
                if name in ctx.extra
            },
            "projection_identity": cls.semantic_projection_identity(ctx),
        }
        normalized = _strict_json_value(canonical)
        if not isinstance(normalized, dict):
            raise TypeError("semantic execution input must be a JSON object")
        return normalized

    @classmethod
    def semantic_fingerprint(cls, ctx: AgentRequestContext) -> str:
        canonical = cls.semantic_execution_input(ctx)
        encoded = json.dumps(
            canonical,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def idempotency_key(ctx: AgentRequestContext) -> str:
        identity = "|".join((
            str(ctx.workspace_id or ""),
            ctx.session_id,
            str(ctx.request_id or ""),
            str(ctx.turn_id or ""),
            str(ctx.generation_id or ""),
            str(ctx.interruption_epoch),
        ))
        return "turn:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _normalize_context_identity(
        trigger: TurnTrigger,
        ctx: AgentRequestContext,
    ) -> AgentRequestContext:
        ctx.sid = str(ctx.sid or trigger).strip() or trigger
        ctx.session_id = str(ctx.session_id or "").strip()
        if not ctx.session_id:
            raise ValueError("semantic turn session_id is required")
        ctx.workspace_id = _optional_text(ctx.workspace_id)
        ctx.request_id = _optional_text(ctx.request_id) or f"turn_{uuid.uuid4().hex[:16]}"
        ctx.turn_id = (
            _optional_text(ctx.turn_id)
            or _optional_text(ctx.extra.get("turn_id"))
            or f"turn:{ctx.request_id}"
        )
        ctx.generation_id = (
            _optional_text(ctx.generation_id)
            or _optional_text(ctx.extra.get("generation_id"))
            or f"generation:{ctx.turn_id}"
        )
        ctx.interruption_epoch = max(
            0,
            int(ctx.interruption_epoch or ctx.extra.get("interruption_epoch", 0) or 0),
        )
        ctx.extra["turn_trigger"] = trigger
        ctx.extra["turn_id"] = ctx.turn_id
        ctx.extra["generation_id"] = ctx.generation_id
        ctx.extra["interruption_epoch"] = ctx.interruption_epoch
        return ctx

    @staticmethod
    def _generation_is_current(ctx: AgentRequestContext, generation: Any) -> bool:
        cancel_signal = getattr(generation, "cancel", None)
        if bool(getattr(generation, "invalidated", False)):
            return False
        if cancel_signal is not None and bool(cancel_signal.is_set()):
            return False
        if str(getattr(generation, "generation_id", "") or "") != str(ctx.generation_id or ""):
            return False
        if int(getattr(generation, "interruption_epoch", 0) or 0) != ctx.interruption_epoch:
            return False
        manager = ctx.generation_mgr
        get_active = getattr(manager, "get", None)
        return not callable(get_active) or get_active(ctx.session_id) is generation

    async def execute(
        self,
        trigger: TurnTrigger | str,
        request: SemanticTurnRequest | Mapping[str, Any],
    ) -> TurnCommit:
        normalized_trigger = self._trigger(trigger)
        ctx = self.build_context(normalized_trigger, request)
        return await self._execute_prepared(normalized_trigger, ctx, apply_bind_context=True)

    async def run(
        self,
        trigger: TurnTrigger | str,
        request: SemanticTurnRequest | Mapping[str, Any],
    ) -> TurnCommit:
        """Compatibility spelling for callers that expose a ``run`` facade."""
        return await self.execute(trigger, request)

    async def execute_context(
        self,
        trigger: TurnTrigger | str,
        ctx: AgentRequestContext,
    ) -> TurnCommit:
        """Execute a context created by HTTP, Socket.IO, voice, or a scheduler.

        Existing runtime dependencies remain attached to ``ctx``. The service
        does not rebuild or re-bind that context unless the caller uses the
        mapping-based ``execute`` adapter.
        """
        normalized_trigger = self._trigger(trigger)
        if not isinstance(ctx, AgentRequestContext):
            raise TypeError("execute_context expects AgentRequestContext")
        self._normalize_context_identity(normalized_trigger, ctx)
        return await self._execute_prepared(normalized_trigger, ctx, apply_bind_context=True)

    async def execute_streaming_context(
        self,
        trigger: TurnTrigger | str,
        ctx: AgentRequestContext,
        stream_adapter: Any,
        generation: Any,
    ) -> TurnCommit:
        """Execute a pre-built context through the pipeline's streaming lane."""
        normalized_trigger = self._trigger(trigger)
        streaming_port = self.ports.run_streaming
        if streaming_port is None:
            raise RuntimeError("streaming turn runner is not configured")
        if not isinstance(ctx, AgentRequestContext):
            raise TypeError("execute_streaming_context expects AgentRequestContext")
        ctx.generation_id = ctx.generation_id or str(
            getattr(generation, "generation_id", "")
            or _optional_text(ctx.extra.get("generation_id"))
            or f"generation:{ctx.turn_id}"
        )
        self._normalize_context_identity(normalized_trigger, ctx)
        terminal_messages: list[dict[str, Any]] = []
        supports_commit_ordering = callable(getattr(stream_adapter, "send_json", None))
        bound_context = ctx

        class _CommitOrderedStreamAdapter:
            async def send_json(self, message: Mapping[str, Any]) -> None:
                event = dict(message)
                if not TurnService._generation_is_current(bound_context, generation):
                    return
                if event.get("type") == "done":
                    terminal_messages[:] = [event]
                    return
                if stream_adapter is not None:
                    await stream_adapter.send_json(event)

        ordered_adapter = _CommitOrderedStreamAdapter()

        def streaming_runner(current: AgentRequestContext) -> AgentPipelineResult | Awaitable[AgentPipelineResult]:
            nonlocal bound_context
            bound_context = current
            adapter = ordered_adapter if supports_commit_ordering else stream_adapter
            return streaming_port(current, adapter, generation)

        replay_delivered = False

        async def deliver_replay(
            _current: AgentRequestContext,
            result: AgentPipelineResult,
        ) -> None:
            nonlocal replay_delivered
            if not self._generation_is_current(_current, generation):
                return
            reply = result.reply
            generation.tokens = [reply] if reply else []
            if result.pet_control is not None:
                generation.pet_control = deepcopy(result.pet_control)
            if stream_adapter is None:
                return
            replay_delivered = True
            if reply:
                await stream_adapter.send_json({
                    "type": "token",
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "content": reply,
                    "replayed": True,
                })
            if result.pet_control is not None:
                await stream_adapter.send_json({
                    "type": "pet_control",
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "pet_control": deepcopy(result.pet_control),
                    "replayed": True,
                })
            await stream_adapter.send_json({
                "type": "done",
                "session_id": generation.session_id,
                "generation_id": generation.generation_id,
                "content": reply,
                "replayed": True,
            })

        commit = await self._execute_prepared(
            normalized_trigger,
            ctx,
            apply_bind_context=True,
            runner=streaming_runner,
            replay_deliverer=deliver_replay,
        )
        if (
            not replay_delivered
            and supports_commit_ordering
            and self._generation_is_current(commit.context, generation)
        ):
            terminal = terminal_messages[-1] if terminal_messages else {
                "type": "done",
                "session_id": getattr(generation, "session_id", ctx.session_id),
                "generation_id": getattr(
                    generation,
                    "generation_id",
                    ctx.extra.get("generation_id"),
                ),
                "content": commit.result.reply,
            }
            await stream_adapter.send_json(terminal)
        return commit

    async def _execute_prepared(
        self,
        normalized_trigger: TurnTrigger,
        ctx: AgentRequestContext,
        *,
        apply_bind_context: bool,
        runner: TurnRunner | None = None,
        replay_deliverer: TurnReplayDeliverer | None = None,
    ) -> TurnCommit:
        release_runtime_context: Callable[[], Any] | None = None
        if apply_bind_context and self.ports.bind_context is not None:
            ctx = await _await_if_needed(self.ports.bind_context(ctx))
            if not isinstance(ctx, AgentRequestContext):
                raise TypeError("turn context binder must return AgentRequestContext")
            release_candidate = ctx.extra.pop("_runtime_context_release", None)
            if callable(release_candidate):
                release_runtime_context = release_candidate
        try:
            return await self._execute_bound_context(
                normalized_trigger,
                ctx,
                runner=runner,
                replay_deliverer=replay_deliverer,
            )
        finally:
            if release_runtime_context is not None:
                await _await_if_needed(release_runtime_context())

    async def _execute_bound_context(
        self,
        normalized_trigger: TurnTrigger,
        ctx: AgentRequestContext,
        *,
        runner: TurnRunner | None,
        replay_deliverer: TurnReplayDeliverer | None,
    ) -> TurnCommit:
        ctx = self._normalize_context_identity(normalized_trigger, ctx)
        key = self.idempotency_key(ctx)
        fingerprint = self.semantic_fingerprint(ctx)
        cached: TurnCommit | None = None
        owns_task = False
        async with self._lock:
            cached = self._commits.get(key)
            if cached is not None:
                if cached.semantic_fingerprint != fingerprint:
                    raise TurnIdentityConflictError(f"semantic turn identity reused with different input: {key}")
                self._commits.move_to_end(key)
                task = None
            else:
                task = self._inflight.get(key)
                if task is None:
                    owns_task = True
                    task = asyncio.create_task(self._execute_once(
                        normalized_trigger,
                        ctx,
                        key,
                        fingerprint,
                        runner,
                        replay_deliverer,
                    ))
                    self._inflight[key] = task
                    self._inflight_fingerprints[key] = fingerprint
                elif self._inflight_fingerprints.get(key) != fingerprint:
                    raise TurnIdentityConflictError(f"in-flight semantic turn identity reused with different input: {key}")
        if cached is not None:
            if self.ports.dispatch is not None:
                await _await_if_needed(self.ports.dispatch(cached))
            if replay_deliverer is not None:
                await _await_if_needed(replay_deliverer(ctx, cached.result))
            return cached
        if task is None:
            raise RuntimeError("turn execution task was not created")
        try:
            commit = await task
            if not owns_task and replay_deliverer is not None:
                await _await_if_needed(replay_deliverer(ctx, commit.result))
            return commit
        finally:
            async with self._lock:
                if self._inflight.get(key) is task and task.done():
                    self._inflight.pop(key, None)
                    self._inflight_fingerprints.pop(key, None)

    async def _execute_once(
        self,
        trigger: TurnTrigger,
        ctx: AgentRequestContext,
        key: str,
        fingerprint: str,
        runner: TurnRunner | None,
        replay_deliverer: TurnReplayDeliverer | None,
    ) -> TurnCommit:
        stored = await self._load_persisted(trigger, ctx, key, fingerprint)
        if stored is not None:
            if self.ports.dispatch is not None:
                await _await_if_needed(self.ports.dispatch(stored))
            if replay_deliverer is not None:
                await _await_if_needed(replay_deliverer(ctx, stored.result))
            await self._remember(stored)
            return stored

        claim_owner: str | None = None
        claim_fencing_token: int | None = None
        renew_task: asyncio.Task[None] | None = None
        claim_lost = asyncio.Event()
        try:
            claim_owner, claim_fencing_token, stored = await self._claim_or_load(
                trigger,
                ctx,
                key,
                fingerprint,
            )
            if stored is not None:
                if self.ports.dispatch is not None:
                    await _await_if_needed(self.ports.dispatch(stored))
                if replay_deliverer is not None:
                    await _await_if_needed(replay_deliverer(ctx, stored.result))
                await self._remember(stored)
                return stored
            if claim_owner is not None and self.ports.renew_claim is not None:
                renew_task = asyncio.create_task(
                    self._renew_claim_loop(
                        key,
                        claim_owner,
                        claim_fencing_token,
                        claim_lost,
                    ),
                    name=f"turn-claim-renew:{key[-12:]}",
                )

            run_task = asyncio.create_task(
                _await_if_needed((runner or self.ports.run)(ctx)),
                name=f"turn-run:{key[-12:]}",
            )
            try:
                if renew_task is None:
                    result = await run_task
                else:
                    lost_task = asyncio.create_task(claim_lost.wait())
                    done, _pending = await asyncio.wait(
                        {run_task, lost_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if lost_task in done and claim_lost.is_set():
                        run_task.cancel()
                        await asyncio.gather(run_task, return_exceptions=True)
                        raise TurnClaimLostError(
                            f"semantic turn claim was lost before commit: {key}"
                        )
                    lost_task.cancel()
                    await asyncio.gather(lost_task, return_exceptions=True)
                    result = await run_task
            except asyncio.CancelledError:
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)
                outcome: TerminalTurnOutcome = (
                    "cancelled" if run_task.cancelled() else "unknown_effect"
                )
                result = AgentPipelineResult(
                    reply="",
                    outcome=outcome,
                    retryable=False,
                    configured_budget=self._configured_budget(ctx),
                )
            if not isinstance(result, AgentPipelineResult):
                raise TypeError("turn runner must return AgentPipelineResult")
            current_task = asyncio.current_task()
            if (
                result.outcome == "completed"
                and current_task is not None
                and current_task.cancelling()
            ):
                result = AgentPipelineResult(
                    reply="",
                    outcome="unknown_effect",
                    retryable=False,
                    configured_budget=(
                        result.configured_budget or self._configured_budget(ctx)
                    ),
                    consumed_usage=result.consumed_usage,
                )
            if not result.configured_budget:
                result.configured_budget = self._configured_budget(ctx)
            if claim_lost.is_set():
                raise TurnClaimLostError(
                    f"semantic turn claim was lost before finalization: {key}"
                )
            if self.ports.finalize is not None:
                try:
                    result = await _await_if_needed(self.ports.finalize(ctx, result))
                except asyncio.CancelledError:
                    result = AgentPipelineResult(
                        reply="",
                        outcome="unknown_effect",
                        retryable=False,
                        configured_budget=self._configured_budget(ctx),
                        consumed_usage=result.consumed_usage,
                    )
                if not isinstance(result, AgentPipelineResult):
                    raise TypeError("turn finalizer must return AgentPipelineResult")
                if not result.configured_budget:
                    result.configured_budget = self._configured_budget(ctx)
            if claim_lost.is_set():
                raise TurnClaimLostError(
                    f"semantic turn claim was lost before persistence: {key}"
                )
            commit = TurnCommit(
                idempotency_key=key,
                semantic_fingerprint=fingerprint,
                trigger=trigger,
                context=ctx,
                result=result,
                claim_owner=claim_owner,
                claim_fencing_token=claim_fencing_token,
            )
            if self.ports.persist is not None:
                commit.persistence_result, _persist_was_cancelled = await _await_durable(
                    self.ports.persist(commit)
                )
                commit.persisted = True
                authority = await self._load_persisted(trigger, ctx, key, fingerprint)
                if authority is not None:
                    commit.result = authority.result
            if self.ports.dispatch is not None:
                try:
                    await _await_if_needed(self.ports.dispatch(commit))
                except asyncio.CancelledError:
                    # The core result is already durable. Projection delivery
                    # remains recoverable through the existing outbox/retry
                    # path, so do not turn a completed turn into a lost one.
                    pass
            await self._remember(commit)
            return commit
        finally:
            if renew_task is not None:
                renew_task.cancel()
                await asyncio.gather(renew_task, return_exceptions=True)
            if (
                claim_owner is not None
                and claim_fencing_token is not None
                and self.ports.release_claim is not None
            ):
                await _await_if_needed(
                    self.ports.release_claim(key, claim_owner, claim_fencing_token)
                )

    async def _load_persisted(
        self,
        trigger: TurnTrigger,
        ctx: AgentRequestContext,
        key: str,
        fingerprint: str,
    ) -> TurnCommit | None:
        if self.ports.load is None:
            return None
        stored = await _await_if_needed(self.ports.load(key))
        if stored is None:
            return None
        stored_fingerprint = str(stored.get("semantic_fingerprint") or "")
        if stored_fingerprint != fingerprint:
            raise TurnIdentityConflictError(
                f"semantic turn identity reused with different input: {key}"
            )
        raw_result = stored.get("result")
        if not isinstance(raw_result, Mapping):
            raise TypeError("durable turn loader returned an invalid result")
        tool_calls = raw_result.get("tool_calls")
        pet_control = raw_result.get("pet_control")
        action_envelope = raw_result.get("action_envelope")
        failure = raw_result.get("failure")
        recovery = raw_result.get("recovery")
        if not isinstance(tool_calls, list) or not all(isinstance(item, dict) for item in tool_calls):
            raise TypeError("durable turn loader returned invalid tool calls")
        if pet_control is not None and not isinstance(pet_control, dict):
            raise TypeError("durable turn loader returned invalid pet control")
        if action_envelope is not None and not isinstance(action_envelope, dict):
            raise TypeError("durable turn loader returned invalid action envelope")
        if failure is not None and not isinstance(failure, dict):
            raise TypeError("durable turn loader returned invalid failure descriptor")
        if recovery is not None and not isinstance(recovery, dict):
            raise TypeError("durable turn loader returned invalid recovery descriptor")
        return TurnCommit(
            idempotency_key=key,
            semantic_fingerprint=fingerprint,
            trigger=trigger,
            context=ctx,
            result=AgentPipelineResult(
                reply=str(raw_result.get("reply") or ""),
                pet_control=deepcopy(pet_control),
                tool_calls=deepcopy(tool_calls),
                action_envelope=deepcopy(action_envelope),
                failure=deepcopy(failure),
                recovery=deepcopy(recovery),
                outcome=self._stored_outcome(raw_result.get("outcome")),
                retryable=bool(raw_result.get("retryable", False)),
                configured_budget=deepcopy(raw_result.get("configured_budget") or {}),
                consumed_usage=deepcopy(raw_result.get("consumed_usage") or {}),
            ),
            persisted=True,
            persistence_result={
                "stored": True,
                "replayed": True,
                "idempotency_key": key,
            },
            replayed=True,
        )

    @staticmethod
    def _configured_budget(ctx: AgentRequestContext) -> dict[str, Any]:
        budget = dict(ctx.extra.get("configured_budget") or {})
        budget.setdefault("output_tokens", max(0, int(ctx.max_tokens)))
        for name in ("max_iterations", "retry_limit", "tool_budget"):
            value = ctx.extra.get(name)
            if value is not None:
                budget.setdefault(name, value)
        return budget

    @staticmethod
    def _stored_outcome(value: Any) -> TerminalTurnOutcome:
        normalized = str(value or "completed")
        if normalized in {"completed", "cancelled", "failed", "unknown_effect"}:
            return normalized  # type: ignore[return-value]
        raise TypeError("durable turn loader returned an invalid terminal outcome")

    async def _claim_or_load(
        self,
        trigger: TurnTrigger,
        ctx: AgentRequestContext,
        key: str,
        fingerprint: str,
    ) -> tuple[str | None, int | None, TurnCommit | None]:
        if self.ports.claim is None:
            return None, None, None
        owner_id = f"claim:{uuid.uuid4().hex}"
        deadline = asyncio.get_running_loop().time() + self.claim_wait_seconds
        while True:
            outcome = await _await_if_needed(
                self.ports.claim(key, fingerprint, owner_id, self.claim_lease_seconds)
            )
            status = str(outcome.get("status") or "")
            if status == "claimed":
                fencing_token = int(outcome.get("fencing_token") or 0)
                if fencing_token <= 0:
                    raise RuntimeError("turn authority returned an invalid fencing token")
                return owner_id, fencing_token, None
            if status == "conflict":
                raise TurnIdentityConflictError(
                    f"semantic turn identity reused with different input: {key}"
                )
            if status not in {"busy", "committed"}:
                raise RuntimeError(f"turn authority returned invalid claim status: {status or '<empty>'}")
            stored = await self._load_persisted(trigger, ctx, key, fingerprint)
            if stored is not None:
                return None, None, stored
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("semantic turn is still executing in another process")
            retry_after = max(0.01, float(outcome.get("retry_after") or 0.05))
            await asyncio.sleep(min(0.1, retry_after, remaining))

    async def _renew_claim_loop(
        self,
        key: str,
        owner_id: str,
        fencing_token: int | None,
        claim_lost: asyncio.Event,
    ) -> None:
        if fencing_token is None:
            claim_lost.set()
            return
        interval = max(0.05, self.claim_lease_seconds / 3.0)
        while True:
            await asyncio.sleep(interval)
            if self.ports.renew_claim is None:
                return
            try:
                renewed = await _await_if_needed(
                    self.ports.renew_claim(
                        key,
                        owner_id,
                        fencing_token,
                        self.claim_lease_seconds,
                    )
                )
            except Exception:
                claim_lost.set()
                raise
            if not renewed:
                claim_lost.set()
                return

    async def _remember(self, commit: TurnCommit) -> None:
        async with self._lock:
            self._commits[commit.idempotency_key] = commit
            self._commits.move_to_end(commit.idempotency_key)
            while len(self._commits) > self.retained_commits:
                self._commits.popitem(last=False)

    async def execute_http(self, request: SemanticTurnRequest | Mapping[str, Any]) -> TurnCommit:
        return await self.execute("http", request)

    async def execute_socket(self, request: SemanticTurnRequest | Mapping[str, Any]) -> TurnCommit:
        return await self.execute("socket", request)

    async def execute_voice(self, request: SemanticTurnRequest | Mapping[str, Any]) -> TurnCommit:
        return await self.execute("voice", request)

    async def execute_scheduler(self, request: SemanticTurnRequest | Mapping[str, Any]) -> TurnCommit:
        return await self.execute("scheduler", request)

    async def execute_heartbeat(self, request: SemanticTurnRequest | Mapping[str, Any]) -> TurnCommit:
        return await self.execute("heartbeat", request)

    def committed(self, idempotency_key: str) -> TurnCommit | None:
        return self._commits.get(idempotency_key)
