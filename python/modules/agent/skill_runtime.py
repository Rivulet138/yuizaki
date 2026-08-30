"""Explicit runtime bindings for imported skill catalog entries.

The catalog is user-editable metadata.  This module is the narrow bridge from
that metadata to an already-registered :class:`ToolDefinition`; it never
executes a handler directly or grants permission.  Every invocation therefore
continues through ``ToolExecutor`` and its existing policy/receipt boundary.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from ..core.paths import data_dir_from_env
from .skill_manifest import (
    SignatureVerifier,
    SkillManifest,
    SkillManifestError,
    verify_skill_package,
)
from .skill_store import SkillCatalogStore
from .skill_trust import SkillTrustStore
from .tool_registry import ToolRegistry
from .tool_result import ToolResultEnvelope

SKILL_RUNTIME_SCHEMA_VERSION = "yuizaki.skill-runtime.v1"
_MAX_AUDIT_ITEMS = 200
_MAX_SCOPE_LENGTH = 160
_AUDIT_REQUIRED_FIELDS = {"eventId", "timestamp", "skillId", "toolName", "status"}
_AUDIT_OPTIONAL_FIELDS = {"detail", "outcome", "retryable", "verificationStatus"}
_AUDIT_STATUSES = {"bound", "bound_verified", "rejected", "unbound", "started", "completed", "failed"}


def _sanitize_audit_item(item: Any) -> dict[str, Any] | None:
    """Accept only the bounded, non-secret audit projection we emit."""
    if not isinstance(item, dict):
        return None
    if "parameters" in item or set(item) - (_AUDIT_REQUIRED_FIELDS | _AUDIT_OPTIONAL_FIELDS):
        return None
    if not _AUDIT_REQUIRED_FIELDS.issubset(item):
        return None
    event_id = item.get("eventId")
    skill_id = item.get("skillId")
    tool_name = item.get("toolName")
    status = item.get("status")
    timestamp = item.get("timestamp")
    if not all(isinstance(value, str) for value in (event_id, skill_id, tool_name, status)):
        return None
    if not event_id or len(event_id) > 160 or not skill_id or len(skill_id) > 160 or len(tool_name) > 160:
        return None
    if status not in _AUDIT_STATUSES or isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    if not math.isfinite(float(timestamp)) or float(timestamp) < 0:
        return None
    sanitized: dict[str, Any] = {
        "eventId": event_id,
        "timestamp": float(timestamp),
        "skillId": skill_id,
        "toolName": tool_name,
        "status": status,
    }
    for field, limit in (("detail", 240), ("outcome", 32), ("verificationStatus", 32)):
        if field in item:
            value = item[field]
            if not isinstance(value, str) or len(value) > limit:
                return None
            sanitized[field] = value
    if "retryable" in item:
        if not isinstance(item["retryable"], bool):
            return None
        sanitized["retryable"] = item["retryable"]
    return sanitized


class SkillRuntimeBindingError(ValueError):
    """Raised when a catalog entry cannot be safely bound to a live tool."""


@dataclass(frozen=True)
class SkillRuntimeBinding:
    skill_id: str
    tool_name: str
    scopes: tuple[str, ...]
    enabled: bool = True
    manifest_version: str | None = None
    package_checksum: str | None = None
    signed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "skillId": self.skill_id,
            "toolName": self.tool_name,
            "scopes": list(self.scopes),
            "enabled": self.enabled,
        }
        if self.manifest_version:
            payload.update({
                "manifestVersion": self.manifest_version,
                "packageChecksum": self.package_checksum,
                "signed": self.signed,
            })
        return payload


class SkillRuntimeRegistry:
    """Manage explicit, in-memory skill-to-tool bindings and audit outcomes."""

    def __init__(
        self,
        catalog_store: SkillCatalogStore,
        tool_registry: ToolRegistry,
        *,
        audit_path: str | Path | None = None,
        trust_store: SkillTrustStore | None = None,
    ) -> None:
        self.catalog_store = catalog_store
        self.tool_registry = tool_registry
        self.trust_store = trust_store
        self._bindings: dict[str, SkillRuntimeBinding] = {}
        self._audit_path = Path(audit_path) if audit_path is not None else data_dir_from_env() / "skill_runtime_audit.json"
        self._audit: list[dict[str, Any]] = []
        self._lock = RLock()
        self._load_audit()

    def _load_audit(self) -> None:
        try:
            payload = json.loads(self._audit_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schemaVersion") != SKILL_RUNTIME_SCHEMA_VERSION:
                self._audit = []
                return
            raw_items = payload.get("items") if isinstance(payload, dict) else None
            if isinstance(raw_items, list):
                self._audit = [item for item in (_sanitize_audit_item(raw) for raw in raw_items) if item is not None][-_MAX_AUDIT_ITEMS:]
        except (OSError, ValueError, TypeError):
            self._audit = []

    def _save_audit(self) -> None:
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": SKILL_RUNTIME_SCHEMA_VERSION,
            "items": self._audit[-_MAX_AUDIT_ITEMS:],
        }
        temporary_path = self._audit_path.with_suffix(f"{self._audit_path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self._audit_path)

    def _record(self, *, skill_id: str, tool_name: str | None, status: str, detail: str = "", result: ToolResultEnvelope | None = None, parameters: dict[str, Any] | None = None) -> None:
        with self._lock:
            data: dict[str, Any] = {
                "eventId": f"skill-exec:{uuid.uuid4().hex}",
                "timestamp": time.time(),
                "skillId": skill_id[:160],
                "toolName": (tool_name or "")[:160],
                "status": status[:48],
            }
            if detail:
                data["detail"] = detail[:240]
            if result is not None:
                data.update({
                    "outcome": str(result.outcome or "")[:32],
                    "retryable": bool(result.retryable),
                    "verificationStatus": str((result.data or {}).get("verificationStatus") or "")[:32] if isinstance(result.data, dict) else "",
                })
            self._audit.append(data)
            self._audit = self._audit[-_MAX_AUDIT_ITEMS:]
            try:
                self._save_audit()
            except OSError:
                # Execution must not fail because a local audit volume is read-only.
                pass

    def bind_tool(self, skill_id: str, tool_name: str, *, scopes: list[str] | tuple[str, ...] = ()) -> SkillRuntimeBinding:
        """Bind only to an already-registered tool and declared tool scopes."""
        return self._bind_tool(skill_id, tool_name, scopes=scopes)

    def _bind_tool(
        self,
        skill_id: str,
        tool_name: str,
        *,
        scopes: list[str] | tuple[str, ...] = (),
        manifest: SkillManifest | None = None,
        verification: dict[str, Any] | None = None,
    ) -> SkillRuntimeBinding:
        skill = self.catalog_store.get(skill_id)
        if skill is None:
            raise SkillRuntimeBindingError(f"unknown skill: {skill_id}")
        normalized_tool_name = str(tool_name).strip()
        tool = self.tool_registry.get(normalized_tool_name)
        if tool is None:
            raise SkillRuntimeBindingError(f"unknown runtime tool: {normalized_tool_name}")
        declared_scopes = {str(scope).strip() for scope in (tool.scopes or []) if str(scope).strip()}
        requested_scopes = tuple(dict.fromkeys(str(scope).strip()[:_MAX_SCOPE_LENGTH] for scope in scopes if str(scope).strip()))
        if any(scope not in declared_scopes for scope in requested_scopes):
            raise SkillRuntimeBindingError("skill scopes must be declared by the target tool")
        binding = SkillRuntimeBinding(
            skill_id=str(skill_id).strip()[:160],
            tool_name=normalized_tool_name[:160],
            scopes=requested_scopes or tuple(sorted(declared_scopes)),
            manifest_version=manifest.version if manifest is not None else None,
            package_checksum=str(verification.get("checksumSha256")) if verification else None,
            signed=bool(verification.get("signed")) if verification else False,
        )
        with self._lock:
            self._bindings[binding.skill_id] = binding
            self.catalog_store.set_runtime_binding(binding.skill_id, tool_name=binding.tool_name, scopes=binding.scopes)
            self._record(
                skill_id=binding.skill_id,
                tool_name=binding.tool_name,
                status="bound_verified" if manifest is not None else "bound",
            )
        return binding

    def bind_verified_tool(
        self,
        skill_id: str,
        tool_name: str,
        *,
        manifest: SkillManifest,
        package_bytes: bytes,
        runtime_version: str,
        verifier: SignatureVerifier | None,
        trust_store: SkillTrustStore | None = None,
        require_signature: bool = True,
    ) -> SkillRuntimeBinding:
        """Bind a package only after manifest identity and signature checks."""
        if manifest.skill_id != str(skill_id).strip():
            raise SkillRuntimeBindingError("skill manifest identity mismatch")
        if manifest.runtime_binding != str(tool_name).strip():
            raise SkillRuntimeBindingError("skill manifest runtime binding mismatch")
        resolved_trust_store = trust_store or self.trust_store
        try:
            verification = (
                resolved_trust_store.verify_manifest(
                    manifest,
                    package_bytes,
                    runtime_version=runtime_version,
                    verifier=verifier,
                )
                if resolved_trust_store is not None
                else verify_skill_package(
                    manifest,
                    package_bytes,
                    runtime_version=runtime_version,
                    verifier=verifier,
                    require_signature=require_signature,
                )
            )
        except SkillManifestError as exc:
            self._record(skill_id=str(skill_id), tool_name=str(tool_name), status="rejected", detail=str(exc))
            raise SkillRuntimeBindingError(str(exc)) from exc
        return self._bind_tool(
            skill_id,
            tool_name,
            scopes=manifest.scopes,
            manifest=manifest,
            verification=verification,
        )

    def unbind(self, skill_id: str) -> bool:
        with self._lock:
            binding = self._bindings.pop(str(skill_id).strip(), None)
            self.catalog_store.clear_runtime_binding(skill_id)
            if binding is None:
                return False
            self._record(skill_id=binding.skill_id, tool_name=binding.tool_name, status="unbound")
            return True

    def resolve(self, skill_id: str) -> SkillRuntimeBinding | None:
        with self._lock:
            binding = self._bindings.get(str(skill_id).strip())
            if binding is None or not binding.enabled:
                return None
            item = self.catalog_store.get(binding.skill_id)
            tool = self.tool_registry.get(binding.tool_name)
            if item is None or item.get("executionReady") is not True or tool is None:
                return None
            if item.get("runtimeTarget") != binding.tool_name:
                return None
            return binding

    async def execute(self, skill_id: str, args: dict[str, Any], *, tool_executor: Any, **execute_kwargs: Any) -> ToolResultEnvelope:
        """Execute a bound skill through the normal policy-aware tool executor."""
        binding = self.resolve(skill_id)
        if binding is None:
            self._record(skill_id=str(skill_id), tool_name=None, status="rejected", detail="skill_not_execution_ready", parameters=args)
            return ToolResultEnvelope(
                success=False,
                content="",
                source="builtin",
                tool_name=str(skill_id),
                error="Skill is not execution-ready",
                data={"code": "SKILL_NOT_EXECUTION_READY"},
                retryable=False,
            )
        execute_kwargs = dict(execute_kwargs)
        execute_kwargs["source"] = f"skill:{binding.skill_id}"
        self._record(skill_id=binding.skill_id, tool_name=binding.tool_name, status="started", parameters=args)
        result = await tool_executor.execute(binding.tool_name, args, **execute_kwargs)
        with self._lock:
            self._record(skill_id=binding.skill_id, tool_name=binding.tool_name, status="completed" if result.success else "failed", result=result)
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schemaVersion": SKILL_RUNTIME_SCHEMA_VERSION,
                "bindings": [binding.to_dict() for binding in self._bindings.values()],
                "audit": {
                    "count": len(self._audit),
                    "recent": [dict(item) for item in self._audit[-20:]],
                },
            }


__all__ = ["SKILL_RUNTIME_SCHEMA_VERSION", "SkillRuntimeBinding", "SkillRuntimeBindingError", "SkillRuntimeRegistry"]
