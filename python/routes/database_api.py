# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from database.repository import DatabaseError, NotFoundError


class MessageUpdateRequest(BaseModel):
    content: str = Field(min_length=1)


def create_database_router(
    get_db_repo: Callable[[], Any],
    get_active_workspace_id: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["database"])

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

    async def _enforce_active_message_workspace(db_repo: Any, message_id: int, workspace_id: str | None = None) -> tuple[str | None, JSONResponse | None]:
        try:
            session_id = await run_in_threadpool(db_repo.get_message_session_id, message_id)
        except NotFoundError as exc:
            return None, JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return None, JSONResponse({"error": str(exc)}, status_code=400)
        guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
        return session_id, guard

    def _session_record_workspace_id(record: dict[str, Any]) -> str:
        return str(record.get("workspace_id") or "default").strip() or "default"

    @router.get("/api/history/{session_id:path}")
    async def get_chat_history(session_id: str, limit: int = 100, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
        if guard is not None:
            return guard
        return {"history": await run_in_threadpool(db_repo.get_chat_history, session_id, limit)}

    @router.get("/api/sessions")
    async def get_all_sessions(scope: str = "active"):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        sessions = await run_in_threadpool(db_repo.get_all_sessions)
        active_workspace_id = _active_workspace_id()
        if active_workspace_id is not None and str(scope or "active").lower() not in {"all", "global"}:
            sessions = [
                session
                for session in sessions
                if _session_record_workspace_id(session) == active_workspace_id
            ]
        return {"sessions": sessions}

    @router.delete("/api/sessions/{session_id:path}/messages")
    async def clear_session_messages(session_id: str, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
        if guard is not None:
            return guard
        try:
            result = await run_in_threadpool(db_repo.clear_session_messages, session_id)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return {"status": "deleted", **result}

    @router.delete("/api/sessions/{session_id:path}")
    async def delete_session(session_id: str, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
        if guard is not None:
            return guard
        await run_in_threadpool(db_repo.delete_session, session_id)
        return {"status": "deleted"}

    @router.delete("/api/messages/{message_id}")
    async def delete_message(message_id: int, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        session_id, guard = await _enforce_active_message_workspace(db_repo, message_id, workspace_id)
        if guard is not None:
            return guard
        try:
            result = await run_in_threadpool(db_repo.delete_message, message_id)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return {"status": "deleted", "session_id": session_id, **result}

    @router.patch("/api/messages/{message_id}")
    async def update_message(message_id: int, payload: MessageUpdateRequest, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        content = payload.content.strip()
        if not content:
            return JSONResponse({"error": "message_content_required"}, status_code=422)
        session_id, guard = await _enforce_active_message_workspace(db_repo, message_id, workspace_id)
        if guard is not None:
            return guard
        try:
            result = await run_in_threadpool(db_repo.update_message, message_id, content)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return {"status": "updated", "session_id": session_id, "message": result}

    @router.delete("/api/messages/{message_id}/after")
    async def delete_messages_after(message_id: int, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        session_id, guard = await _enforce_active_message_workspace(db_repo, message_id, workspace_id)
        if guard is not None:
            return guard
        try:
            result = await run_in_threadpool(db_repo.delete_messages_after, message_id)
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return {"status": "deleted", "session_id": session_id, **result}

    @router.get("/api/statistics")
    async def get_statistics(days: int = 7):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        return {"statistics": await run_in_threadpool(db_repo.get_statistics, days)}

    @router.post("/api/statistics/update")
    async def update_statistics():
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        await run_in_threadpool(db_repo.update_daily_statistics)
        return {"status": "updated"}

    @router.get("/api/database/stats")
    async def get_database_stats():
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        return await run_in_threadpool(db_repo.get_database_stats)

    @router.post("/api/export/json")
    async def export_json(session_id: str | None = None, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        if session_id:
            guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
            if guard is not None:
                return guard
        content = await run_in_threadpool(db_repo.export_to_json, session_id)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=chat_history.json"},
        )

    @router.post("/api/export/csv")
    async def export_csv(session_id: str | None = None, workspace_id: str | None = None):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        if session_id:
            guard = await _enforce_active_session_workspace(db_repo, session_id, workspace_id)
            if guard is not None:
                return guard
        content = await run_in_threadpool(db_repo.export_to_csv, session_id)
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=chat_history.csv"},
        )

    return router
