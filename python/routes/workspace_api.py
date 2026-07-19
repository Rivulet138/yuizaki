# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from database.repository import DatabaseError, NotFoundError


def create_workspace_router(
    get_db_repo: Callable[[], Any],
    get_mcp_manager: Callable[[], Any] | None = None,
    get_active_workspace_id: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["workspace"])

    def _active_workspace_id() -> str | None:
        if get_active_workspace_id is None:
            return None
        workspace_id = str(get_active_workspace_id() or "").strip()
        return workspace_id or None

    async def _enforce_active_session_workspace(db_repo: Any, session_id: str, workspace_id: str | None = None) -> JSONResponse | None:
        requested_workspace_id = str(workspace_id or "").strip() or None
        allowed_workspace_id = requested_workspace_id or _active_workspace_id()
        if allowed_workspace_id is None:
            return None
        try:
            session_workspace_id = await run_in_threadpool(db_repo.get_session_workspace_id, session_id)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if session_workspace_id != allowed_workspace_id:
            return JSONResponse(
                {
                    "error": "workspace_mismatch",
                    "message": "Session does not belong to the active workspace",
                    "active_workspace_id": _active_workspace_id(),
                    "requested_workspace_id": requested_workspace_id,
                    "session_workspace_id": session_workspace_id,
                },
                status_code=403,
            )
        return None

    @router.get("/api/workspaces")
    async def list_workspaces():
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        return {"workspaces": await run_in_threadpool(db_repo.list_workspaces)}

    @router.post("/api/workspaces")
    async def create_workspace(payload: dict[str, Any]):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        workspace_id = str(payload.get("id") or f"ws_{payload.get('name', 'workspace')}").strip()
        try:
            workspace = await run_in_threadpool(
                db_repo.create_workspace,
                workspace_id=workspace_id,
                name=str(payload.get("name") or "新场景"),
                description=payload.get("description"),
            )
            if payload.get("companion_profile_id"):
                workspace = await run_in_threadpool(db_repo.update_workspace, workspace_id, {"companion_profile_id": payload.get("companion_profile_id")})
            return workspace
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.patch("/api/workspaces/{workspace_id:path}")
    async def update_workspace(workspace_id: str, payload: dict[str, Any]):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        try:
            return await run_in_threadpool(db_repo.update_workspace, workspace_id, payload)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.delete("/api/workspaces/{workspace_id:path}")
    async def delete_workspace(workspace_id: str):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        await run_in_threadpool(db_repo.delete_workspace, workspace_id)
        return {"status": "deleted"}

    @router.get("/api/workspaces/{workspace_id:path}/sessions")
    async def list_workspace_sessions(workspace_id: str):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        try:
            sessions = await run_in_threadpool(db_repo.list_workspace_sessions, workspace_id)
            return {"workspace_id": workspace_id, "sessions": sessions}
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.post("/api/workspaces/{workspace_id:path}/sessions")
    async def create_workspace_session(workspace_id: str, payload: dict[str, Any]):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        try:
            return await run_in_threadpool(db_repo.create_chat_session, workspace_id, payload.get("title"))
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.patch("/api/sessions/{session_id}")
    async def update_session(session_id: str, payload: dict[str, Any], workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
        if guard is not None:
            return guard
        try:
            return await run_in_threadpool(
                db_repo.update_chat_session,
                session_id,
                summary=payload.get("summary"),
                pinned=payload.get("pinned"),
                title=payload.get("title"),
            )
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.get("/api/workspaces/{workspace_id:path}/effective-preset")
    async def effective_preset(workspace_id: str):
        """Return the resolved tool allow-list and MCP server config for a workspace."""
        import json as _json
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        workspaces = await run_in_threadpool(db_repo.list_workspaces)
        workspace = next((w for w in workspaces if w.get("id") == workspace_id), None)
        if workspace is None:
            return JSONResponse({"error": f"workspace_not_found: {workspace_id}"}, status_code=404)

        # Resolve tool allow-list
        raw_tool_preset = workspace.get("tool_preset")
        tool_names: list[str] = []
        if isinstance(raw_tool_preset, str) and raw_tool_preset.strip():
            try:
                parsed = _json.loads(raw_tool_preset)
                if isinstance(parsed, list):
                    tool_names = [str(item) for item in parsed if isinstance(item, str)]
            except _json.JSONDecodeError:
                pass

        # Resolve MCP preset
        mcp_preset_id = workspace.get("mcp_preset_id")
        mcp_server: dict[str, Any] | None = None
        if mcp_preset_id and get_mcp_manager is not None:
            manager = get_mcp_manager()
            if manager is not None:
                server = manager.servers.get(mcp_preset_id)
                if server is not None:
                    mcp_server = {
                        "name": server.name,
                        "base_url": server.base_url,
                        "transport": server.transport,
                        "enabled": server.enabled,
                    }

        return {
            "workspace_id": workspace_id,
            "tool_names": tool_names,
            "mcp_preset_id": mcp_preset_id,
            "mcp_server": mcp_server,
        }

    return router
