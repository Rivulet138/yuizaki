from __future__ import annotations

import asyncio
import hashlib
import os
from collections import deque
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from database.repository import DatabaseError
from modules.agent.prompt_assembly import PromptBlock, build_prompt_assembly
from modules.system.memory_write_pipeline import build_user_signal_event
from modules.system.rate_limiter import SlidingWindowRateLimiter


OPENAI_REALTIME_ORIGIN = "https://api.openai.com"
DEFAULT_REALTIME_MODEL = "gpt-realtime-2.1"
DEFAULT_REALTIME_VOICE = "marin"
SUPPORTED_REALTIME_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
}
REALTIME_AGENT_TOOL_NAME = "delegate_to_agent"
REALTIME_AGENT_INTENTS = ["tool", "memory", "vision", "task", "deep_answer"]


class RealtimeSessionRequest(BaseModel):
    workspace_id: str | None = None
    session_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class RealtimeTranscriptRequest(BaseModel):
    workspace_id: str | None = None
    session_id: str = Field(min_length=1, max_length=240)
    turn_id: str = Field(min_length=1, max_length=240)
    user_text: str = Field(min_length=1, max_length=12000)
    assistant_text: str = Field(min_length=1, max_length=12000)
    tool_trace: list[dict[str, Any]] | None = None
    memory_trace: list[dict[str, Any]] | None = None

    model_config = ConfigDict(extra="forbid")


def _is_official_openai_base_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname == "api.openai.com"


def resolve_realtime_api_key(config: Any) -> str:
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    llm = getattr(config, "llm", None)
    provider = str(getattr(llm, "provider", "") or "").strip().lower()
    base_url = str(getattr(llm, "base_url", "") or "").strip()
    if provider not in {"chatgpt", "openai"} and not _is_official_openai_base_url(base_url):
        return ""
    return str(getattr(llm, "api_key", "") or "").strip()


def resolve_realtime_model() -> str:
    return os.getenv("YUIZAKI_REALTIME_MODEL", DEFAULT_REALTIME_MODEL).strip() or DEFAULT_REALTIME_MODEL


def resolve_realtime_voice() -> str:
    requested = os.getenv("YUIZAKI_REALTIME_VOICE", DEFAULT_REALTIME_VOICE).strip().lower()
    return requested if requested in SUPPORTED_REALTIME_VOICES else DEFAULT_REALTIME_VOICE


def build_realtime_instructions(
    *,
    db_repo: Any,
    workspace_id: str,
    session_id: str,
) -> str:
    compiled = build_prompt_assembly(
        db_repo=db_repo,
        generation_mgr=None,
        workspace_id=workspace_id,
        session_id=session_id,
        messages=[],
        response_mode="instant",
        additional_blocks=[
            PromptBlock(
                block_id="realtime_voice_boundary",
                source="backend",
                trust="trusted",
                authority="policy",
                order=225,
                content=(
                    "This is the low-latency voice companion lane. Respond in the user's language with short, "
                    "natural speech. For requests that need tools, screen evidence, durable memory, file changes, "
                    "or a longer task, call delegate_to_agent instead of inventing an execution result. Wait for "
                    "the tool result, then summarize it naturally. Do not call the tool for ordinary conversation."
                ),
            )
        ],
    )
    return "\n\n".join(
        str(message.get("content") or "").strip()
        for message in compiled
        if message.get("role") == "system" and str(message.get("content") or "").strip()
    )


def resolve_realtime_safety_identifier(api_key: str) -> str:
    configured = os.getenv("YUIZAKI_OPENAI_SAFETY_IDENTIFIER", "").strip()
    if configured:
        return configured[:128]
    digest = hashlib.sha256(f"yuizaki-local:{api_key}".encode("utf-8")).hexdigest()
    return f"yuizaki_{digest[:32]}"


def build_realtime_session_config(*, model: str, voice: str, instructions: str) -> dict[str, Any]:
    return {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "output_modalities": ["audio"],
        "max_output_tokens": 1024,
        "tool_choice": "auto",
        "tools": [
            {
                "type": "function",
                "name": REALTIME_AGENT_TOOL_NAME,
                "description": (
                    "Delegate a request to Yuizaki's local Agent runtime when it needs MCP tools, durable memory, "
                    "screen vision, external actions, or a longer multi-step answer."
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "request": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 12000,
                            "description": "The complete user request to execute or answer.",
                        },
                        "intent": {
                            "type": "string",
                            "enum": REALTIME_AGENT_INTENTS,
                            "description": "Why the full Agent runtime is required.",
                        },
                    },
                    "required": ["request", "intent"],
                },
            }
        ],
        "audio": {
            "input": {
                "transcription": {
                    "model": "gpt-4o-mini-transcribe",
                    "language": "zh",
                },
                "noise_reduction": {"type": "near_field"},
                "turn_detection": None,
            },
            "output": {
                "voice": voice,
                "speed": 1.0,
            },
        },
    }


async def mint_realtime_client_secret(
    *,
    api_key: str,
    model: str,
    voice: str,
    instructions: str,
) -> dict[str, Any]:
    session = build_realtime_session_config(model=model, voice=voice, instructions=instructions)
    async with httpx.AsyncClient(
        base_url=OPENAI_REALTIME_ORIGIN,
        timeout=httpx.Timeout(15.0, connect=5.0),
    ) as client:
        response = await client.post(
            "/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "OpenAI-Safety-Identifier": resolve_realtime_safety_identifier(api_key),
            },
            json={"session": session},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not str(payload.get("value") or "").startswith("ek_"):
        raise ValueError("OpenAI did not return a Realtime client secret")
    return payload


def create_realtime_router(
    *,
    get_config: Callable[[], Any],
    get_db_repo: Callable[[], Any],
    get_active_workspace_id: Callable[[], str],
    get_relationship_writer: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/realtime", tags=["realtime"])
    mint_limiter = SlidingWindowRateLimiter(max_requests=8, window_seconds=60.0)
    persisted_turns: set[str] = set()
    persisted_turn_order: deque[str] = deque()
    transcript_lock = asyncio.Lock()

    def resolve_workspace(requested: str | None) -> tuple[str, JSONResponse | None]:
        active = str(get_active_workspace_id() or "").strip() or "default"
        clean_requested = str(requested or "").strip()
        if clean_requested and clean_requested != active:
            return active, JSONResponse(
                {
                    "error": "workspace_mismatch",
                    "message": "Realtime workspace does not match the active workspace",
                    "active_workspace_id": active,
                },
                status_code=403,
            )
        return active, None

    async def create_client_secret(payload: RealtimeSessionRequest, request: Request):
        workspace_id, workspace_error = resolve_workspace(payload.workspace_id)
        if workspace_error is not None:
            return workspace_error

        rate_key = f"{request.client.host if request.client else 'unknown'}:{workspace_id}"
        rate = mint_limiter.check(rate_key)
        if not rate.allowed:
            return JSONResponse(
                {"error": "rate_limited", "retry_after": rate.retry_after},
                status_code=429,
                headers={"Retry-After": str(max(1, int(rate.retry_after)))},
            )

        config = get_config()
        api_key = resolve_realtime_api_key(config)
        if not api_key:
            return JSONResponse(
                {
                    "error": "realtime_not_configured",
                    "message": "OpenAI Realtime requires OPENAI_API_KEY or an official OpenAI LLM provider",
                },
                status_code=409,
            )

        session_id = str(payload.session_id or "").strip() or "default"
        model = resolve_realtime_model()
        voice = resolve_realtime_voice()
        instructions = await run_in_threadpool(
            build_realtime_instructions,
            db_repo=get_db_repo(),
            workspace_id=workspace_id,
            session_id=session_id,
        )
        try:
            upstream = await mint_realtime_client_secret(
                api_key=api_key,
                model=model,
                voice=voice,
                instructions=instructions,
            )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300] if exc.response.text else ""
            return JSONResponse(
                {
                    "error": "realtime_upstream_error",
                    "message": f"OpenAI Realtime returned HTTP {exc.response.status_code}",
                    "detail": detail,
                },
                status_code=502,
            )
        except (httpx.RequestError, ValueError) as exc:
            return JSONResponse(
                {"error": "realtime_unavailable", "message": str(exc)},
                status_code=503,
            )

        return {
            "client_secret": str(upstream["value"]),
            "expires_at": upstream.get("expires_at"),
            "model": model,
            "voice": voice,
            "agent_model": str(getattr(getattr(config, "llm", None), "model", "") or ""),
            "workspace_id": workspace_id,
            "session_id": session_id,
        }

    async def persist_transcript(payload: RealtimeTranscriptRequest):
        workspace_id, workspace_error = resolve_workspace(payload.workspace_id)
        if workspace_error is not None:
            return workspace_error
        async with transcript_lock:
            if payload.turn_id in persisted_turns:
                return {"status": "duplicate", "turn_id": payload.turn_id}

            db_repo = get_db_repo()
            if db_repo is None:
                return JSONResponse({"error": "database_not_initialized"}, status_code=503)

            user_text = payload.user_text.strip()
            assistant_text = payload.assistant_text.strip()
            if not user_text or not assistant_text:
                return JSONResponse({"error": "transcript_text_required"}, status_code=422)

            model = resolve_realtime_model()
            try:
                user_message, assistant_message = await run_in_threadpool(
                    db_repo.save_message_pair,
                    payload.session_id,
                    user_text,
                    assistant_text,
                    model=model,
                    workspace_id=workspace_id,
                    tool_trace=payload.tool_trace,
                    memory_trace=payload.memory_trace,
                )
            except DatabaseError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

            persisted_turns.add(payload.turn_id)
            persisted_turn_order.append(payload.turn_id)
            while len(persisted_turn_order) > 256:
                persisted_turns.discard(persisted_turn_order.popleft())

            if get_relationship_writer is not None:
                writer = get_relationship_writer()
                relationship_event = build_user_signal_event(user_text)
                if writer and relationship_event:
                    await run_in_threadpool(writer, relationship_event)

            return {
                "status": "saved",
                "turn_id": payload.turn_id,
                "user_message": user_message,
                "assistant_message": assistant_message,
            }

    router.add_api_route("/client-secret", create_client_secret, methods=["POST"])
    router.add_api_route("/transcript", persist_transcript, methods=["POST"])
    return router
