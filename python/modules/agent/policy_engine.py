from __future__ import annotations

from dataclasses import dataclass
import asyncio
import uuid
import json
from datetime import datetime
from pathlib import Path

from ..core.paths import data_dir_from_env
from .models import PermissionAuditRecord
from .tool_registry import ToolDefinition


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = "ok"
    request_id: str | None = None
    require_confirm: bool = False


class PolicyEngine:
    """最小权限策略引擎。

    当前策略：
    - safe / low：允许
    - 任何 require_confirm=True 且 risk_level in (medium/high/critical)：默认拒绝
    """

    def __init__(self, store_file: str | Path | None = None) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._remembered: dict[str, bool] = {}
        self._audit: list[dict[str, object]] = []
        self._audit_max_entries = 500
        self._store_file = Path(store_file) if store_file is not None else data_dir_from_env() / "permissions.json"
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
        self._audit.append(entry)
        if len(self._audit) > self._audit_max_entries:
            self._audit = self._audit[-self._audit_max_entries:]
        self._save_store()

    def get_remembered_decisions(self) -> dict[str, bool]:
        return dict(self._remembered)

    def _build_scope_key(self, tool_name: str, permission_scope: str | None = None) -> str:
        scope = (permission_scope or "default").strip() or "default"
        return f"{tool_name}::{scope}"

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
        self._save_store()
        return True

    def clear(self) -> int:
        count = len(self._remembered)
        self._remembered.clear()
        self._append_audit(PermissionAuditRecord(
            timestamp=datetime.now().isoformat(),
            decision="cleared",
        ).to_dict())
        self._save_store()
        return count

    def evaluate_tool(self, tool: ToolDefinition, request_id: str | None = None, permission_scope: str | None = None) -> PolicyDecision:
        scope_key = self._build_scope_key(tool.name, permission_scope)
        remembered = self._remembered.get(scope_key)
        if remembered is not None:
            self._append_audit(PermissionAuditRecord(
                timestamp=datetime.now().isoformat(),
                tool_name=tool.name,
                capability_id=tool.name,
                capability_type="tool",
                capability_kind=f"{tool.source}-tool",
                remember_scope=(permission_scope or "default").strip() or "default",
                decision="remembered_allow" if remembered else "remembered_deny",
                risk_level=tool.risk_level,
                request_id=request_id,
                requires_approval=bool(tool.require_confirm),
            ).to_dict())
            return PolicyDecision(allowed=remembered, reason="remembered")

        if tool.require_confirm and tool.risk_level in {"medium", "high", "critical"}:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Tool '{tool.name}' requires user confirmation "
                    f"(risk={tool.risk_level}) before execution"
                ),
                request_id=f"perm_{uuid.uuid4().hex[:12]}",
                require_confirm=True,
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
        ).to_dict())
        return PolicyDecision(allowed=True)

    def register_pending(self, request_id: str) -> asyncio.Future[bool]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future
        return future

    def resolve_pending(self, request_id: str, allowed: bool, remember: bool = False, tool_name: str | None = None, permission_scope: str | None = None) -> None:
        future = self._pending.pop(request_id, None)
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
        ).to_dict())
        if remember and tool_name:
            self._save_store()
