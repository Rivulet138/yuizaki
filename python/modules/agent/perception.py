"""Permission-aware, request-scoped perception provider boundary."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

PerceptionCapability = Literal[
    "screenshot", "target_window", "active_application", "ocr",
    "selected_file", "clipboard", "notification", "calendar", "camera",
]
CollectionMode = Literal["request", "user_selected", "disabled"]


class PerceptionPermissionError(PermissionError):
    pass


class PerceptionProviderError(RuntimeError):
    pass


class PerceptionCancelledError(PerceptionProviderError):
    pass


@dataclass(frozen=True)
class PerceptionProviderSpec:
    name: str
    capability: PerceptionCapability | str
    requires_permission: bool = True
    collection_mode: CollectionMode = "request"
    ttl_seconds: float = 15.0
    max_payload_bytes: int = 2_000_000
    supports_redaction: bool = False
    storage_policy: Literal["ephemeral", "session", "durable"] = "ephemeral"
    selection_metadata_key: str = "selection_token"
    requires_host_provenance: bool = False

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("provider name is required")
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if self.max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if self.collection_mode == "disabled":
            object.__setattr__(self, "requires_permission", True)


@dataclass(frozen=True)
class PerceptionRequest:
    workspace_id: str
    session_id: str
    turn_id: str
    capability: PerceptionCapability | str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    generation_id: str = ""
    interruption_epoch: int = 0
    issued_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    redaction: bool = True
    max_payload_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    cancellation_signal: Any | None = field(default=None, repr=False, compare=False)
    consent: object | None = field(default=None, repr=False, compare=False)
    selection_authority: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for key in ("workspace_id", "session_id", "turn_id", "capability"):
            if not str(getattr(self, key) or "").strip():
                raise ValueError(f"{key} is required")
        if self.max_payload_bytes is not None and self.max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if not str(self.request_id or "").strip():
            raise ValueError("request_id is required")
        if not str(self.generation_id or "").strip():
            object.__setattr__(self, "generation_id", f"generation:{self.request_id}")
        if self.interruption_epoch < 0:
            raise ValueError("interruption_epoch must be non-negative")
        if self.expires_at is not None and self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")

    @property
    def cancelled(self) -> bool:
        signal = self.cancellation_signal
        if signal is None:
            return False
        checker = getattr(signal, "is_set", None)
        if callable(checker):
            return bool(checker())
        return bool(getattr(signal, "cancelled", False))


@dataclass(frozen=True)
class PerceptionEvidence:
    evidence_id: str
    provider: str
    capability: str
    workspace_id: str
    session_id: str
    turn_id: str
    payload: Any
    captured_at: float
    expires_at: float
    redacted: bool
    provenance: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = ""
    generation_id: str = ""
    interruption_epoch: int = 0

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class PerceptionProvider(Protocol):
    spec: PerceptionProviderSpec

    async def collect(self, request: PerceptionRequest) -> PerceptionEvidence | Mapping[str, Any] | Any: ...


PermissionChecker = Callable[[PerceptionRequest, PerceptionProviderSpec], bool | Awaitable[bool]]
ProviderFactory = Callable[[PerceptionRequest], PerceptionEvidence | Mapping[str, Any] | Any | Awaitable[Any]]


class PerceptionConsentAuthority:
    """Mint and consume opaque, single-use consent bound to one request scope."""

    def __init__(self) -> None:
        self._issued: dict[object, tuple[str, str, str, str, str, str, int, str, float]] = {}

    def issue(
        self,
        *,
        workspace_id: str,
        sid: str,
        session_id: str,
        turn_id: str,
        request_id: str,
        generation_id: str,
        interruption_epoch: int,
        capability: str,
        ttl_seconds: float = 15.0,
    ) -> object:
        consent = object()
        self._issued[consent] = (
            workspace_id, sid, session_id, turn_id, request_id, generation_id,
            interruption_epoch, capability, time.time() + max(0.1, ttl_seconds),
        )
        return consent

    def consume(self, request: PerceptionRequest, spec: PerceptionProviderSpec) -> bool:
        consent = request.consent
        if consent is None:
            return False
        scope = self._issued.pop(consent, None)
        if scope is None:
            return False
        expected = (
            request.workspace_id, str(request.metadata.get("sid") or ""),
            request.session_id, request.turn_id, request.request_id,
            request.generation_id, request.interruption_epoch, str(spec.capability),
        )
        if scope[:8] != expected or time.time() >= scope[8]:
            return False
        if spec.collection_mode == "user_selected" and request.selection_authority is not consent:
            return False
        return True


def _payload_size(payload: Any) -> int:
    if isinstance(payload, bytes):
        return len(payload)
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(payload).encode("utf-8"))


_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|authorization|password|passwd|secret|private[_-]?key|cookie)",
    re.IGNORECASE,
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)
_FORBIDDEN_AUTHORITY_KEYS = frozenset({
    "authorized", "authorization", "approval", "permission_receipt", "execution_permit",
    "tool_scope", "action_scope", "confirmation_token",
})


def redact_sensitive_payload(value: Any) -> Any:
    """Return a bounded-shape copy with common credentials removed."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_sensitive_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_payload(item) for item in value)
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_TEXT_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def _assert_not_cancelled(request: PerceptionRequest) -> None:
    if request.cancelled:
        raise PerceptionCancelledError("perception request was cancelled")


async def _collect_with_cancellation(
    provider: PerceptionProvider,
    request: PerceptionRequest,
) -> PerceptionEvidence | Mapping[str, Any] | Any:
    signal_wait = getattr(request.cancellation_signal, "wait", None)
    timeout = None if request.expires_at is None else max(0.0, request.expires_at - time.time())
    if not callable(signal_wait) and timeout is None:
        return await provider.collect(request)

    async def invoke_provider() -> PerceptionEvidence | Mapping[str, Any] | Any:
        return await provider.collect(request)

    async def wait_for_cancellation(waiter: Callable[[], object]) -> None:
        outcome = waiter()
        if inspect.isawaitable(outcome):
            await outcome

    provider_task = asyncio.create_task(invoke_provider())
    cancellation_task = asyncio.create_task(wait_for_cancellation(signal_wait)) if callable(signal_wait) else None
    waiters: set[asyncio.Task[Any]] = {provider_task}
    if cancellation_task is not None:
        waiters.add(cancellation_task)
    try:
        done, _pending = await asyncio.wait(
            waiters,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if provider_task in done:
            return await provider_task
        provider_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await provider_task
        if cancellation_task is not None and cancellation_task in done:
            raise PerceptionCancelledError("perception request was cancelled")
        raise PerceptionProviderError("perception request expired during collection")
    finally:
        if cancellation_task is not None:
            cancellation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancellation_task


def _validate_untrusted_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(provenance)
    forbidden = sorted(_FORBIDDEN_AUTHORITY_KEYS.intersection(str(key) for key in normalized))
    if forbidden:
        raise PerceptionProviderError(
            f"perception evidence cannot carry action authority: {', '.join(forbidden)}"
        )
    normalized["trust"] = "untrusted"
    normalized["authority"] = "evidence"
    return normalized


@dataclass
class CallablePerceptionProvider:
    spec: PerceptionProviderSpec
    collector: ProviderFactory

    async def collect(self, request: PerceptionRequest) -> Any:
        result = self.collector(request)
        return await result if inspect.isawaitable(result) else result


class PerceptionProviderRegistry:
    def __init__(self, permission_checker: PermissionChecker | None = None) -> None:
        self._providers: dict[str, PerceptionProvider] = {}
        self._permission_checker = permission_checker

    def register(self, provider: PerceptionProvider) -> None:
        spec = getattr(provider, "spec", None)
        if not isinstance(spec, PerceptionProviderSpec):
            raise TypeError("provider.spec must be PerceptionProviderSpec")
        name = spec.name.strip()
        if name in self._providers:
            raise ValueError(f"perception provider already registered: {name}")
        self._providers[name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(str(name).strip(), None)

    def get(self, name: str) -> PerceptionProvider | None:
        return self._providers.get(str(name).strip())

    def providers(self) -> tuple[PerceptionProviderSpec, ...]:
        return tuple(provider.spec for provider in self._providers.values())

    async def collect(self, provider_name: str, request: PerceptionRequest) -> PerceptionEvidence:
        _assert_not_cancelled(request)
        if request.expires_at is not None and time.time() >= request.expires_at:
            raise PerceptionProviderError("perception request expired before collection")
        provider = self.get(provider_name)
        if provider is None:
            raise PerceptionProviderError(f"unknown perception provider: {provider_name}")
        spec = provider.spec
        if spec.capability != request.capability:
            raise PerceptionProviderError(
                f"provider {spec.name!r} does not support capability {request.capability!r}"
            )
        if spec.collection_mode == "disabled":
            raise PerceptionPermissionError(f"perception provider disabled: {spec.name}")
        if spec.collection_mode == "user_selected" and request.selection_authority is None:
            raise PerceptionPermissionError(f"perception provider requires explicit user selection: {spec.name}")
        permission_required = spec.requires_permission or str(spec.capability) in {
            "screenshot", "target_window", "active_application", "ocr", "clipboard", "camera",
        }
        if permission_required:
            if self._permission_checker is None:
                raise PerceptionPermissionError(f"permission required for perception provider: {spec.name}")
            allowed = self._permission_checker(request, spec)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not allowed:
                raise PerceptionPermissionError(f"permission denied for perception provider: {spec.name}")
        result = await _collect_with_cancellation(provider, request)
        _assert_not_cancelled(request)
        now = time.time()
        if request.expires_at is not None and now >= request.expires_at:
            raise PerceptionProviderError("perception request expired before evidence was returned")
        limit = min(spec.max_payload_bytes, request.max_payload_bytes or spec.max_payload_bytes)
        if isinstance(result, PerceptionEvidence):
            if any((
                result.workspace_id != request.workspace_id,
                result.session_id != request.session_id,
                result.turn_id != request.turn_id,
                result.request_id != request.request_id,
                result.generation_id != request.generation_id,
                result.interruption_epoch != request.interruption_epoch,
            )):
                raise PerceptionProviderError("provider returned evidence for a different request scope")
            if result.provider != spec.name or result.capability != str(spec.capability):
                raise PerceptionProviderError("provider returned evidence with mismatched identity")
            if result.expired or result.captured_at < request.issued_at or result.expires_at > result.captured_at + spec.ttl_seconds:
                raise PerceptionProviderError("provider returned expired evidence")
            must_redact = request.redaction or str(request.capability) in {
                "screenshot", "target_window", "active_application", "ocr", "selected_file", "clipboard",
            }
            payload = redact_sensitive_payload(result.payload) if must_redact else result.payload
            if _payload_size(payload) > limit:
                raise PerceptionProviderError(f"perception payload exceeds {limit} bytes")
            image_payload = str(request.capability) in {"screenshot", "target_window"}
            return PerceptionEvidence(
                evidence_id=result.evidence_id,
                provider=result.provider,
                capability=result.capability,
                workspace_id=result.workspace_id,
                session_id=result.session_id,
                turn_id=result.turn_id,
                payload=payload,
                captured_at=result.captured_at,
                expires_at=result.expires_at,
                redacted=must_redact and not image_payload,
                provenance=_validate_untrusted_provenance(result.provenance),
                request_id=result.request_id,
                generation_id=result.generation_id,
                interruption_epoch=result.interruption_epoch,
            )
        if spec.requires_host_provenance:
            if not isinstance(result, Mapping):
                raise PerceptionProviderError("host perception provider returned an invalid evidence envelope")
            expected_identity = {
                "provider": spec.name,
                "capability": str(spec.capability),
                "workspace_id": request.workspace_id,
                "session_id": request.session_id,
                "turn_id": request.turn_id,
                "request_id": request.request_id,
                "generation_id": request.generation_id,
                "interruption_epoch": request.interruption_epoch,
            }
            mismatched = [key for key, expected in expected_identity.items() if result.get(key) != expected]
            if mismatched:
                raise PerceptionProviderError(
                    f"host evidence identity mismatch: {', '.join(mismatched)}"
                )
        payload = result.get("payload") if isinstance(result, Mapping) and "payload" in result else result
        must_redact = request.redaction or str(request.capability) in {
            "screenshot", "target_window", "active_application", "ocr", "selected_file", "clipboard",
        }
        payload = redact_sensitive_payload(payload) if must_redact else payload
        encoded_size = _payload_size(payload)
        if encoded_size > limit:
            raise PerceptionProviderError(f"perception payload exceeds {limit} bytes")
        captured_at = float(result.get("captured_at") or now) if isinstance(result, Mapping) else now
        expires_at = float(result.get("expires_at") or (captured_at + spec.ttl_seconds)) if isinstance(result, Mapping) else captured_at + spec.ttl_seconds
        if captured_at < request.issued_at or captured_at > now + 1.0:
            raise PerceptionProviderError("provider returned evidence outside the request lifetime")
        if expires_at <= now or expires_at > captured_at + spec.ttl_seconds:
            raise PerceptionProviderError("provider returned invalid evidence expiry")
        provenance = _validate_untrusted_provenance(
            dict(result.get("provenance") or {}) if isinstance(result, Mapping) else {}
        )
        provenance.update({"provider": spec.name, "request_id": request.request_id, "collection_mode": spec.collection_mode})
        image_payload = str(request.capability) in {"screenshot", "target_window"}
        return PerceptionEvidence(
            evidence_id=str(result.get("evidence_id") or uuid.uuid4().hex) if isinstance(result, Mapping) else uuid.uuid4().hex,
            provider=spec.name,
            capability=str(spec.capability),
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            payload=payload,
            captured_at=captured_at,
            expires_at=expires_at,
            redacted=must_redact and not image_payload,
            provenance=provenance,
            request_id=request.request_id,
            generation_id=request.generation_id,
            interruption_epoch=request.interruption_epoch,
        )
