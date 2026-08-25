from __future__ import annotations

from dataclasses import dataclass
import asyncio
import uuid
import json
import threading
from datetime import datetime
from pathlib import Path

from ..core.paths import data_dir_from_env
from .models import PermissionAuditRecord
from .permission_receipt import (
    PermissionDecision,
    PermissionReceipt,
    build_permission_receipt,
)
from .tool_registry import ToolDefinition


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = "ok"
    request_id: str | None = None
    require_confirm: bool = False
    permission_receipt: PermissionReceipt | None = None


class PolicyEngine:
    """最小权限策略引擎。

    当前策略：
    - safe / low：允许
    - medium：由工具所属服务或插件的启用选择授权
    - require_confirm=True 或 high / critical：请求用户确认
    """

    def __init__(self, store_file: str | Path | None = None) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._permission_metadata: dict[str, dict[str, str]] = {}
        self._remembered: dict[str, bool] = {}
        self._audit: list[dict[str, object]] = []
        self._audit_max_entries = 500
        self._store_file = Path(store_file) if store_file is not None else data_dir_from_env() / "permissions.json"
        self._store_lock = threading.RLock()
        self._load_store()

    def _load_store(self) -> None:
        try:
            if not self._store_file.exists():
                return
            data = json.loads(self._store_file.read_text(encoding="utf-8"))
            remembered = data.get("remembered") or {}
            audit = data.get("audit") or []
            if isinstance(remembered, dict):
                self._remembered = {str(k): bool(v) for k, v in remembered.items()}
            if isinstance(audit, list):
                self._audit = [item for item in audit if isinstance(item, dict)][-self._audit_max_entries:]
        except Exception:
            self._remembered = {}
            self._audit = []

    def _save_store(self) -> None:
        with self._store_lock:
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            self._store_file.write_text(
                json.dumps(
                    {
                        "remembered": self._remembered,
                        "audit": self._audit[-self._audit_max_entries:],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def _append_audit(self, entry: dict[str, object]) -> None:
        with self._store_lock:
            self._audit.append(entry)
            if len(self._audit) > self._audit_max_entries:
                self._audit = self._audit[-self._audit_max_entries:]
            self._save_store()

    def get_remembered_decisions(self) -> dict[str, bool]:
        return dict(self._remembered)

    def _build_scope_key(self, tool_name: str, permission_scope: str | None = None) -> str:
        scope = (permission_scope or "default").strip() or "default"
        return f"{tool_name}::{scope}"

    @staticmethod
    def _is_selected_external_tool(tool: ToolDefinition) -> bool:
        """MCP/plugin enablement is the authorization decision for that tool."""
        return tool.source in {"mcp", "plugin"} and not tool.require_confirm

    def get_audit_log(self, limit: int = 100) -> list[dict[str, object]]:
        take = max(1, min(int(limit), self._audit_max_entries))
        return self._audit[-take:]

    def revoke(self, tool_name: str, permission_scope: str | None = None) -> bool:
        raw_tool_name = str(tool_name or "").strip()
        if permission_scope is None and "::" in raw_tool_name and raw_tool_name in self._remembered:
            key = raw_tool_name
            remembered_scope = raw_tool_name.split("::", 1)[1]
            audit_tool_name = raw_tool_name.split("::", 1)[0]
        else:
            key = self._build_scope_key(raw_tool_name, permission_scope)
            remembered_scope = (permission_scope or "default").strip() or "default"
            audit_tool_name = raw_tool_name or None
        if not key or key not in self._remembered:
            return False
        self._remembered.pop(key, None)
        self._append_audit(PermissionAuditRecord(
            timestamp=datetime.now().isoformat(),
            tool_name=audit_tool_name,
            remember_scope=remembered_scope,
            decision="revoked",
        ).to_dict())
        return True

    def clear(self) -> int:
        count = len(self._remembered)
        self._remembered.clear()
        self._append_audit(PermissionAuditRecord(
            timestamp=datetime.now().isoformat(),
            decision="cleared",
        ).to_dict())
        return count

    def preview_tool(
        self,
        tool: ToolDefinition,
        request_id: str | None = None,
        permission_scope: str | None = None,
        parameters: object | None = None,
        force_confirm: bool = False,
    ) -> PolicyDecision:
        """Return the current policy outcome without creating control-plane state."""

        del request_id, parameters
        if self._is_selected_external_tool(tool):
            return PolicyDecision(allowed=True)
        scope_key = self._build_scope_key(tool.name, permission_scope)
        remembered = self._remembered.get(scope_key)
        if remembered is True and not tool.allow_remembered_decision:
            remembered = None
        if remembered is not None and (not force_confirm or remembered is False):
            return PolicyDecision(allowed=remembered, reason="remembered")
        if force_confirm or tool.require_confirm or tool.risk_level in {"high", "critical"}:
            return PolicyDecision(
                allowed=False,
                reason=(
                    "untrusted_mcp_followup_requires_confirmation"
                    if force_confirm
                    else "permission_required"
                ),
                require_confirm=True,
            )
        return PolicyDecision(allowed=True)

    def evaluate_tool(
        self,
        tool: ToolDefinition,
        request_id: str | None = None,
        permission_scope: str | None = None,
        parameters: object | None = None,
        force_confirm: bool = False,
    ) -> PolicyDecision:
        agent_request_id = str(request_id or f"agent_{uuid.uuid4().hex[:12]}")
        scope = (permission_scope or "default").strip() or "default"
        permission_request_id = f"perm_{uuid.uuid4().hex[:12]}"
        capability_call_id = f"call_{uuid.uuid4().hex[:12]}"

        if self._is_selected_external_tool(tool):
            return PolicyDecision(allowed=True)

        def receipt(decision: PermissionDecision, reason_code: str, *, retryable: bool) -> PermissionReceipt:
            return build_permission_receipt(
                agent_request_id=agent_request_id,
                permission_request_id=permission_request_id,
                capability_call_id=capability_call_id,
                decision=decision,
                reason_code=reason_code,
                retryable=retryable,
                permission_scope=scope,
                capability_id=tool.name,
                capability_type="tool",
                capability_kind=f"{tool.source}-tool",
                risk_level=tool.risk_level,
                parameters=parameters or {},
            )

        preview = self.preview_tool(
            tool,
            request_id=request_id,
            permission_scope=permission_scope,
            parameters=parameters,
            force_confirm=force_confirm,
        )
        if preview.reason == "remembered":
            self._append_audit(PermissionAuditRecord(
                timestamp=datetime.now().isoformat(),
                tool_name=tool.name,
                capability_id=tool.name,
                capability_type="tool",
                capability_kind=f"{tool.source}-tool",
                remember_scope=(permission_scope or "default").strip() or "default",
                decision="remembered_allow" if preview.allowed else "remembered_deny",
                risk_level=tool.risk_level,
                request_id=request_id,
                requires_approval=bool(tool.require_confirm),
                agent_request_id=agent_request_id,
                permission_request_id=permission_request_id,
                capability_call_id=capability_call_id,
                permission_scope=scope,
            ).to_dict())
            return PolicyDecision(
                allowed=preview.allowed,
                reason="remembered",
                permission_receipt=receipt(
                    "allowed" if preview.allowed else "denied",
                    "remembered_allow" if preview.allowed else "remembered_deny",
                    retryable=bool(preview.allowed),
                ),
            )

        if preview.require_confirm:
            reason_code = "untrusted_mcp_followup_requires_confirmation" if force_confirm else "permission_required"
            with self._store_lock:
                self._permission_metadata[permission_request_id] = {
                    "agent_request_id": agent_request_id,
                    "capability_call_id": capability_call_id,
                    "permission_scope": scope,
                }
            self._append_audit(PermissionAuditRecord(
                timestamp=datetime.now().isoformat(),
                tool_name=tool.name,
                capability_id=tool.name,
                capability_type="tool",
                capability_kind=f"{tool.source}-tool",
                remember_scope=scope,
                decision="required",
                risk_level=tool.risk_level,
                request_id=request_id,
                requires_approval=True,
                agent_request_id=agent_request_id,
                permission_request_id=permission_request_id,
                capability_call_id=capability_call_id,
                permission_scope=scope,
            ).to_dict())
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Tool '{tool.name}' requires user confirmation "
                    f"(risk={tool.risk_level}) before execution"
                ),
                request_id=permission_request_id,
                require_confirm=True,
                permission_receipt=receipt("required", reason_code, retryable=False),
            )

        self._append_audit(PermissionAuditRecord(
            timestamp=datetime.now().isoformat(),
            tool_name=tool.name,
            capability_id=tool.name,
            capability_type="tool",
            capability_kind=f"{tool.source}-tool",
            remember_scope=(permission_scope or "default").strip() or "default",
            decision="auto_allow",
            risk_level=tool.risk_level,
            request_id=request_id,
            requires_approval=bool(tool.require_confirm),
            agent_request_id=agent_request_id,
            permission_request_id=permission_request_id,
            capability_call_id=capability_call_id,
            permission_scope=scope,
        ).to_dict())
        return PolicyDecision(
            allowed=preview.allowed,
            permission_receipt=receipt("allowed", "policy_auto_allow", retryable=True),
        )

    def register_pending(self, request_id: str) -> asyncio.Future[bool]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future
        return future

    def discard_permission(self, request_id: str) -> None:
        with self._store_lock:
            self._permission_metadata.pop(request_id, None)

    def resolve_pending(self, request_id: str, allowed: bool, remember: bool = False, tool_name: str | None = None, permission_scope: str | None = None) -> None:
        future = self._pending.pop(request_id, None)
        with self._store_lock:
            metadata = self._permission_metadata.pop(request_id, {})
        if future and not future.done():
            future.set_result(allowed)
        if remember and tool_name:
            self._remembered[self._build_scope_key(tool_name, permission_scope)] = allowed
        self._append_audit(PermissionAuditRecord(
            timestamp=datetime.now().isoformat(),
            request_id=request_id,
            tool_name=tool_name,
            capability_id=tool_name,
            capability_type="tool" if tool_name else None,
            capability_kind=None,
            remember_scope=(permission_scope or "default").strip() or "default",
            decision="allowed" if allowed else "denied",
            remember=remember,
            agent_request_id=metadata.get("agent_request_id"),
            permission_request_id=request_id,
            capability_call_id=metadata.get("capability_call_id"),
            permission_scope=metadata.get("permission_scope") or permission_scope,
        ).to_dict())
