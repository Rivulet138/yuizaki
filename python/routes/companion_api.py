# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from database.repository import DatabaseError, NotFoundError


class CompanionVoiceProfile(BaseModel):
    ref_audio: str | None = None
    ref_text: str | None = None
    lang: Literal["zh", "ja", "en", "auto"] | None = None
    base_url: str | None = None

    model_config = ConfigDict(extra="forbid")


class CompanionPayload(BaseModel):
    id: str | None = None
    name: str | None = None
    avatar: str | None = None
    model_type: Literal["live2d", "vrm"] | None = None
    model_id: str | None = None
    voice_profile: CompanionVoiceProfile | None = None
    persona_prompt: str | None = None
    temperament: Literal["warm", "playful", "reserved"] | None = None
    attachment_style: Literal["secure", "attached", "independent"] | None = None
    support_style: Literal["gentle", "analytical", "cheerful"] | None = None
    emotion_state: str | None = None
    affinity_state: float | None = Field(default=None, ge=0, le=1)
    energy_state: float | None = Field(default=None, ge=0, le=1)
    trust_state: float | None = Field(default=None, ge=0, le=1)
    intimacy_state: float | None = Field(default=None, ge=0, le=1)
    interruptibility_state: float | None = Field(default=None, ge=0, le=1)
    fatigue_state: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")


def create_companion_router(
    get_db_repo: Callable[[], Any],
    relationship_history_handler: Callable[[str, int], Any] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["companion"])

    @router.get("/api/companions")
    async def list_companions():
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        return {"companions": await run_in_threadpool(db_repo.list_companions)}

    if relationship_history_handler is not None:
        @router.get("/api/companions/{companion_id:path}/relationship-history")
        async def get_companion_relationship_history(companion_id: str, limit: int = 20):
            return await run_in_threadpool(relationship_history_handler, companion_id, limit)

    @router.get("/api/companions/{companion_id:path}")
    async def get_companion(companion_id: str):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        companion = await run_in_threadpool(db_repo.get_companion, companion_id)
        if not companion:
            return JSONResponse({"error": "companion_not_found"}, status_code=404)
        return companion

    @router.post("/api/companions")
    async def create_companion(payload: CompanionPayload):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        payload_dict = payload.model_dump(exclude_none=True)
        companion_id = str(payload_dict.get("id") or f"comp_{payload_dict.get('name', 'companion')}").strip()
        name = str(payload_dict.get("name") or "新結崎")
        kwargs = {k: v for k, v in payload_dict.items() if k not in ("id", "name") and v is not None}
        try:
            return await run_in_threadpool(db_repo.create_companion, companion_id=companion_id, name=name, **kwargs)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.patch("/api/companions/{companion_id:path}")
    async def update_companion(companion_id: str, payload: CompanionPayload):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        try:
            return await run_in_threadpool(db_repo.update_companion, companion_id, payload.model_dump(exclude_none=True))
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @router.delete("/api/companions/{companion_id:path}")
    async def delete_companion(companion_id: str):
        db_repo = get_db_repo()
        if not db_repo:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        try:
            impacted_workspaces = await run_in_threadpool(db_repo.list_workspaces_referencing_companion, companion_id)
            await run_in_threadpool(db_repo.delete_companion, companion_id)
            return {"status": "deleted", "fallback_companion_id": "default", "rebound_workspaces": impacted_workspaces}
        except NotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except DatabaseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    return router
