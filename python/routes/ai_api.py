# pyright: reportUnusedFunction=false

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from modules.agent import AgentRuntime
from modules.agent.context import AgentRequestContext, bind_runtime_bindings
from modules.agent.permission_receipt import serialize_permission_payload
from modules.agent.turn_service import TurnClaimLostError, TurnIdentityConflictError
from modules.system.api_response import error_response
from modules.system.memory_write_pipeline import build_user_signal_event
from pydantic import BaseModel, ConfigDict, Field
from state.schemas import ChatCompletionRequest

MAX_SVC_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_READ_CHUNK_BYTES = 64 * 1024


class UploadTooLargeError(Exception):
    pass


class RecoveryResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_handle: str = Field(min_length=8, max_length=160)
    workspace_id: str | None = Field(default=None, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=200)
    failed_step_id: str = Field(min_length=1, max_length=160)


def _chat_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message.startswith("LLM API "):
        return message
    return "Chat completion failed"


def _stream_error_contract(
    exc: Exception,
    *,
    request_id: str | None,
    turn_id: str | None,
) -> dict[str, Any]:
    """Map stream failures to the same stable envelope used by JSON APIs.

    Streaming responses cannot change their HTTP status after headers are sent,
    so the event itself carries the retry decision and turn identity.  Keep the
    legacy ``error`` field for existing clients while making retryability
    explicit instead of treating every exception as transient.
    """
    message = _chat_error_message(exc)
    code = "chat_completion_failed"
    retryable = False
    status = 500
    if isinstance(exc, TurnIdentityConflictError):
        code, message, status = "turn_identity_conflict", "Turn identity conflicts with an existing request", 409
    elif isinstance(exc, TurnClaimLostError):
        code, message, status = "turn_claim_lost", "Turn execution claim was lost", 409
    elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        code, message, retryable, status = "upstream_timeout", "Chat completion timed out", True, 504
    elif isinstance(exc, (ConnectionError, OSError)):
        code, message, retryable, status = "upstream_unavailable", "Chat provider is temporarily unavailable", True, 503
    else:
        lowered = str(exc).lower()
        if "unknown effect" in lowered or "external effect" in lowered:
            code, message = "unknown_effect", "External effect status is unknown; manual review is required"
        elif "permission" in lowered or "confirmation" in lowered:
            code, message = "permission_required", "Additional permission or confirmation is required"
        elif "workspace" in lowered and ("mismatch" in lowered or "active" in lowered):
            code, message, status = "workspace_mismatch", "Chat workspace does not match the active workspace", 403
        elif "not initialized" in lowered or "not configured" in lowered or "unavailable" in lowered:
            code, message, retryable, status = "service_unavailable", "Chat service is temporarily unavailable", True, 503
    payload: dict[str, Any] = {
        "error": code,
        "code": code,
        "message": message,
        "retryable": retryable,
        "status_code": status,
    }
    if request_id:
        payload["request_id"] = request_id
    if turn_id:
        payload["turn_id"] = turn_id
    return payload


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        read_size = min(UPLOAD_READ_CHUNK_BYTES, max_bytes + 1 - total)
        chunk = await file.read(read_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


def create_ai_router(
    get_config: Callable[[], Any],
    get_generation_mgr: Callable[[], Any],
    get_llm_client: Callable[[], Any],
    get_svc_client: Callable[[], Any],
    get_agent_runtime: Callable[[], AgentRuntime],
    get_db_repo: Callable[[], Any],
    get_relationship_writer: Callable[[], Any],
    get_relationship_history: Callable[[], Any],
    get_relationship_summary: Callable[[], Any],
    logger,
    get_active_workspace_id: Callable[[], str] | None = None,
    allow_legacy_turn_pipeline: bool = False,
) -> APIRouter:
    router = APIRouter(tags=["ai"])
    legacy_warning_emitted = False

    def _maybe_write_user_relationship_event(
        messages: list[dict[str, Any]],
        writer: Any,
        *,
        workspace_id: str | None,
        turn_id: str | None,
    ) -> None:
        if not writer:
            return
        user_text = ""
        for item in reversed(messages):
            if item.get('role') == 'user':
                user_text = str(item.get('content') or '')
                break
        event = build_user_signal_event(
            user_text,
            workspace_id=workspace_id,
            turn_id=turn_id,
        )
        if event:
            writer(event)

    async def _write_user_relationship_event(
        messages: list[dict[str, Any]],
        *,
        workspace_id: str | None,
        turn_id: str | None,
    ) -> None:
        await asyncio.to_thread(
            _maybe_write_user_relationship_event,
            messages,
            get_relationship_writer(),
            workspace_id=workspace_id,
            turn_id=turn_id,
        )

    async def _bind_runtime_context(ctx: AgentRequestContext) -> AgentRequestContext:
        relationship_history = await asyncio.to_thread(get_relationship_history)
        relationship_summary = await asyncio.to_thread(get_relationship_summary)
        return bind_runtime_bindings(
            ctx,
            db_repo=get_db_repo(),
            relationship_event_writer=get_relationship_writer(),
            relationship_history=relationship_history or [],
            relationship_summary=relationship_summary or {},
        )

    def _as_text(value: Any, default: str = "") -> str:
        return value if isinstance(value, str) else default

    def _as_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        if not isinstance(value, (str, int, float)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _as_optional_int(value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, (str, int, float)):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _payload_options(payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("chat_options")
        return raw if isinstance(raw, dict) else {}

    def _resolve_chat_workspace_id(requested_workspace_id: str | None) -> tuple[str | None, JSONResponse | None]:
        requested = requested_workspace_id.strip() if isinstance(requested_workspace_id, str) else ""
        if get_active_workspace_id is None:
            return requested or None, None

        active_workspace_id = str(get_active_workspace_id() or "").strip() or "default"
        if requested and requested != active_workspace_id:
            return None, error_response(
                code="workspace_mismatch",
                message="Chat workspace does not match the active workspace",
                status_code=403,
                details={"active_workspace_id": active_workspace_id},
                legacy_fields={"active_workspace_id": active_workspace_id},
            )
        return active_workspace_id, None

    def _resolve_chat_session_id(requested_session_id: str | None) -> str:
        requested = requested_session_id.strip() if isinstance(requested_session_id, str) else ""
        return requested or uuid.uuid4().hex[:12]

    def _require_turn_service(runtime: Any) -> Any | None:
        nonlocal legacy_warning_emitted
        turn_service = getattr(runtime, "turn_service", None)
        if turn_service is None and not allow_legacy_turn_pipeline:
            raise RuntimeError("TurnService is required for semantic chat execution")
        if turn_service is None and allow_legacy_turn_pipeline and not legacy_warning_emitted:
            logger.warning(
                "Legacy HTTP Turn pipeline is enabled; chat requests may bypass "
                "TurnService/outbox and should be migrated."
            )
            legacy_warning_emitted = True
        return turn_service

    def _bind_http_generation(
        generation_mgr: Any,
        session_id: str,
        request_id: str,
    ) -> Any:
        turn_id = f"turn:{request_id}"
        generation_id = f"generation:{turn_id}"
        try:
            return generation_mgr.start(
                session_id,
                request_id=request_id,
                turn_id=turn_id,
                generation_id=generation_id,
                interruption_epoch=0,
            )
        except TypeError:
            generation = generation_mgr.start(session_id)
            generation.request_id = request_id
            generation.turn_id = turn_id
            generation.generation_id = generation_id
            generation.interruption_epoch = 0
            return generation

    def _commit_metadata(commit: Any) -> dict[str, Any]:
        ctx = commit.context
        metadata = {
            "idempotency_key": commit.idempotency_key,
            "semantic_fingerprint": commit.semantic_fingerprint,
            "turn_stage": "committed",
            "outcome": commit.outcome,
            "retryable": bool(commit.retryable),
            "replayed": bool(commit.replayed),
            "projection_pending": bool(getattr(commit, "projection_pending", False)),
            "workspace_id": ctx.workspace_id,
            "session_id": ctx.session_id,
            "request_id": ctx.request_id,
            "turn_id": ctx.turn_id,
            "generation_id": ctx.generation_id,
            "interruption_epoch": ctx.interruption_epoch,
        }
        failure = getattr(commit.result, "failure", None)
        recovery = getattr(commit.result, "recovery", None)
        if isinstance(failure, dict):
            metadata["failure"] = dict(failure)
        if isinstance(recovery, dict):
            metadata["recovery"] = dict(recovery)
        return metadata

    def _build_http_schedule_context(task: Any, sid: str) -> AgentRequestContext:
        runtime = get_agent_runtime()
        llm_client = get_llm_client()
        generation_mgr = get_generation_mgr()
        ctx = AgentRequestContext(
            sid=sid,
            session_id=f"schedule:{task.id}",
            messages=[{"role": "user", "content": task.prompt}],
            llm_client=llm_client,
            generation_mgr=generation_mgr,
            tool_registry=runtime.tool_registry,
            tool_executor=runtime.tool_executor,
            step_executor=runtime.step_executor,
            scheduler=runtime.scheduler,
            trace_store=runtime.trace_store,
            plugin_manager=runtime.plugin_manager,
        )
        return bind_runtime_bindings(
            ctx,
            db_repo=get_db_repo(),
            relationship_event_writer=get_relationship_writer(),
            relationship_history=get_relationship_history() or [],
            relationship_summary=get_relationship_summary() or {},
        )

    @router.get("/v1/models")
    @router.post("/v1/models")
    async def list_models():
        config = get_config()
        return {"object": "list", "data": [{"id": config.llm.model, "object": "model"}]}

    @router.post("/api/agent/recovery/resume")
    async def resume_agent_recovery(req: RecoveryResumeRequest):
        workspace_id, workspace_error = _resolve_chat_workspace_id(req.workspace_id)
        if workspace_error is not None:
            return workspace_error
        runtime = get_agent_runtime()
        step_executor = getattr(runtime, "step_executor", None)
        resume = getattr(step_executor, "resume_recovery_handle", None)
        if not callable(resume):
            return error_response(
                code="recovery_not_available",
                message="Recovery is not available in the current runtime",
                status_code=503,
            )
        try:
            resume_fn = cast(Callable[..., Awaitable[dict[str, Any]]], resume)
            result = await resume_fn(
                req.recovery_handle,
                workspace_id=workspace_id,
                session_id=req.session_id,
                turn_id=req.turn_id,
                failed_step_id=req.failed_step_id,
            )
        except Exception as exc:
            logger.error("Recovery resume failed: %s", exc, exc_info=True)
            return error_response(code="recovery_resume_failed", message="Recovery resume failed", status_code=500)
        if not isinstance(result, dict):
            return error_response(code="recovery_resume_invalid", message="Recovery resume returned an invalid result", status_code=500)
        recovery_error = str(result.get("error") or "").strip()
        if recovery_error:
            status_code = {
                "invalid_or_expired_recovery_handle": 409,
                "recovery_in_progress": 409,
                "durable_recovery_not_allowed": 409,
                "recovery_context_missing": 409,
                "recovery_context_invalid": 409,
                "recovery_context_unavailable": 503,
                "recovery_turn_service_unavailable": 503,
                "recovery_not_available": 503,
            }.get(recovery_error, 500)
            return error_response(
                code=recovery_error,
                message=(
                    "The recovery handle is invalid or expired"
                    if recovery_error == "invalid_or_expired_recovery_handle"
                    else "Recovery could not be resumed"
                ),
                status_code=status_code,
                details={
                    key: result[key]
                    for key in ("recovery", "recovery_id", "attempt")
                    if key in result
                },
                legacy_error=recovery_error,
            )
        result.pop("resume_token", None)
        return JSONResponse(result)

    @router.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        workspace_id, workspace_error = _resolve_chat_workspace_id(req.workspace_id)
        if workspace_error is not None:
            return workspace_error

        runtime = get_agent_runtime()
        llm_client = get_llm_client()
        generation_mgr = get_generation_mgr()
        pipeline = runtime.agent_pipeline
        tool_registry = runtime.tool_registry
        tool_executor = runtime.tool_executor
        step_executor = runtime.step_executor
        trace_store = runtime.trace_store
        plugin_manager = runtime.plugin_manager
        scheduler = runtime.scheduler
        if not llm_client:
            return error_response(
                code="llm_not_initialized",
                message="LLM client is not initialized",
                status_code=503,
                legacy_error="LLM client not initialized",
            )
        if req.stream:
            async def stream_generator():
                session_id = _resolve_chat_session_id(req.session_id)
                request_id = req.request_id or f"agent_{uuid.uuid4().hex[:12]}"
                turn_id = f"turn:{request_id}"
                try:
                    messages = [m.model_dump() for m in req.messages]
                    gen = _bind_http_generation(generation_mgr, session_id, request_id)
                    turn_id = gen.turn_id
                    ctx = AgentRequestContext(
                        sid="http-stream",
                        session_id=session_id,
                        request_id=request_id,
                        turn_id=gen.turn_id,
                        generation_id=gen.generation_id,
                        interruption_epoch=gen.interruption_epoch,
                        messages=messages,
                        workspace_id=workspace_id,
                        model=req.model,
                        temperature=req.temperature,
                        top_p=req.top_p,
                        top_k=req.top_k,
                        min_p=req.min_p,
                        frequency_penalty=req.frequency_penalty,
                        presence_penalty=req.presence_penalty,
                        repetition_penalty=req.repetition_penalty,
                        max_tokens=req.max_tokens or 65535,
                        reasoning_effort=req.reasoning_effort,
                        mcp_enabled=req.mcp_enabled,
                        web_search_enabled=req.web_search_enabled,
                        pet_control_context=req.pet_control_context.model_dump() if req.pet_control_context else None,
                        llm_client=llm_client,
                        generation_mgr=generation_mgr,
                        tool_registry=tool_registry,
                        tool_executor=tool_executor,
                        step_executor=step_executor,
                        scheduler=scheduler,
                        trace_store=trace_store,
                        plugin_manager=plugin_manager,
                        permission_scope="http:chat-completions",
                        autonomy_mode=req.autonomy_mode,
                    )
                    if req.autonomy_mode != "silent":
                        ctx = await _bind_runtime_context(ctx)
                    turn_service = _require_turn_service(runtime)
                    commit: Any | None = None
                    if turn_service is None:
                        if req.autonomy_mode != "silent":
                            await _write_user_relationship_event(
                                messages,
                                workspace_id=workspace_id,
                                turn_id=ctx.turn_id,
                            )
                        result_obj = await pipeline.run_streaming(ctx, None, gen)
                    else:
                        executed_commit = await turn_service.execute_streaming_context(
                            "http", ctx, None, gen,
                        )
                        commit = executed_commit
                        result_obj = executed_commit.result
                    final_reply = result_obj.reply
                    if result_obj.action_envelope:
                        yield f"data: {json.dumps({'action_envelope': serialize_permission_payload(result_obj.action_envelope)})}\n\n"
                    terminal: dict[str, Any] = {
                        "choices": [{"delta": {"content": final_reply}, "finish_reason": "stop"}],
                        "outcome": result_obj.outcome,
                        "retryable": result_obj.retryable,
                    }
                    if commit is not None:
                        terminal["turn_commit"] = _commit_metadata(commit)
                    yield f"data: {json.dumps(terminal)}\n\n"
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Chat error: %s", e, exc_info=True)
                    error_payload = _stream_error_contract(
                        e,
                        request_id=request_id,
                        turn_id=turn_id,
                    )
                    yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({
                        'choices': [{'delta': {'content': ''}, 'finish_reason': 'error'}],
                        'outcome': 'failed',
                        'retryable': bool(error_payload['retryable']),
                        'code': error_payload['code'],
                        'request_id': request_id,
                        'turn_id': turn_id,
                    })}\n\n"
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        session_id = _resolve_chat_session_id(req.session_id)
        try:
            messages = [m.model_dump() for m in req.messages]
            request_id = req.request_id or f"agent_{uuid.uuid4().hex[:12]}"
            turn_id = f"turn:{request_id}"
            generation_id = f"generation:{turn_id}"
            ctx = AgentRequestContext(
                sid="http",
                session_id=session_id,
                request_id=request_id,
                turn_id=turn_id,
                generation_id=generation_id,
                interruption_epoch=0,
                messages=messages,
                workspace_id=workspace_id,
                model=req.model,
                temperature=req.temperature,
                top_p=req.top_p,
                top_k=req.top_k,
                min_p=req.min_p,
                frequency_penalty=req.frequency_penalty,
                presence_penalty=req.presence_penalty,
                repetition_penalty=req.repetition_penalty,
                max_tokens=req.max_tokens or 65535,
                reasoning_effort=req.reasoning_effort,
                mcp_enabled=req.mcp_enabled,
                web_search_enabled=req.web_search_enabled,
                pet_control_context=req.pet_control_context.model_dump() if req.pet_control_context else None,
                llm_client=llm_client,
                generation_mgr=generation_mgr,
                tool_registry=tool_registry,
                tool_executor=tool_executor,
                step_executor=step_executor,
                scheduler=scheduler,
                trace_store=trace_store,
                plugin_manager=plugin_manager,
                permission_scope="http:chat-completions",
                autonomy_mode=req.autonomy_mode,
            )
            if req.autonomy_mode != "silent":
                ctx = await _bind_runtime_context(ctx)
            turn_service = _require_turn_service(runtime)
            commit: Any | None = None
            if turn_service is None:
                if req.autonomy_mode != "silent":
                    await _write_user_relationship_event(
                        messages,
                        workspace_id=workspace_id,
                        turn_id=ctx.turn_id,
                    )
                result = await pipeline.run(ctx)
            else:
                executed_commit = await turn_service.execute_context("http", ctx)
                commit = executed_commit
                result = executed_commit.result
            response_payload: dict[str, Any] = {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": result.reply,
                    }
                }]
            }
            if result.pet_control:
                response_payload["pet_control"] = result.pet_control
            if result.action_envelope:
                response_payload["action_envelope"] = serialize_permission_payload(result.action_envelope)
            if commit is not None:
                response_payload["turn_commit"] = _commit_metadata(commit)
            return JSONResponse(response_payload)
        except Exception as e:
            logger.error("Chat error: %s", e, exc_info=True)
            return error_response(code="chat_error", message=_chat_error_message(e), status_code=500)

    @router.post("/api/chat/translate")
    async def translate_text(payload: dict[str, Any]):
        llm_client = get_llm_client()
        if not llm_client:
            return error_response(
                code="llm_not_initialized",
                message="LLM client is not initialized",
                status_code=503,
                legacy_error="LLM client not initialized",
            )

        text = _as_text(payload.get("text")).strip()
        if not text:
            return error_response(
                code="text_required",
                message="text is required",
                status_code=422,
                legacy_error="text is required",
            )

        target_language = _as_text(payload.get("target_language"), "zh-CN").strip() or "zh-CN"
        source_language = _as_text(payload.get("source_language"), "auto").strip() or "auto"
        options = _payload_options(payload)

        try:
            result = await llm_client.complete_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是严格的翻译引擎。只输出译文，不要解释。"
                            "保留原文的 Markdown、列表、代码块、变量名和专有名词；"
                            "代码块内容不翻译，代码块外的自然语言翻译为目标语言。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"源语言：{source_language}\n目标语言：{target_language}\n\n{text}",
                    },
                ],
                max_output_tokens=_as_optional_int(options.get("max_tokens")) or 1600,
                model=_as_text(options.get("model")) or None,
                temperature=_as_optional_float(options.get("temperature")) if options.get("temperature") is not None else 0.2,
                top_p=_as_optional_float(options.get("top_p")),
                top_k=_as_optional_int(options.get("top_k")),
                min_p=_as_optional_float(options.get("min_p")),
                frequency_penalty=_as_optional_float(options.get("frequency_penalty")),
                presence_penalty=_as_optional_float(options.get("presence_penalty")),
                repetition_penalty=_as_optional_float(options.get("repetition_penalty")),
                reasoning_effort=_as_text(options.get("reasoning_effort")) or None,
            )
            return {"translated_text": str(result.get("reply") or "").strip()}
        except Exception as e:
            logger.error("Translate error: %s", e)
            return error_response(code="translate_error", message="Translation failed", status_code=500)

    @router.post("/svc/convert")
    async def svc_convert(
        file: UploadFile = File(...),
        speaker_id: int | None = Form(None),
        pitch: int | None = Form(None),
    ):
        svc_client = get_svc_client()
        if not svc_client:
            return error_response(
                code="svc_not_initialized",
                message="SVC client is not initialized",
                status_code=503,
                legacy_error="SVC client not initialized",
            )
        try:
            content = await _read_upload_limited(file, MAX_SVC_UPLOAD_BYTES)
            audio_base64 = base64.b64encode(content).decode()
            generation_id = f"svc_{uuid.uuid4().hex[:10]}"
            result = await svc_client.convert(
                generation_id,
                audio_base64,
                speaker_id=speaker_id,
                pitch=pitch,
            )
            return result
        except UploadTooLargeError:
            return error_response(
                code="file_too_large",
                message="Uploaded file exceeds the size limit",
                status_code=413,
                details={"max_bytes": MAX_SVC_UPLOAD_BYTES},
                legacy_fields={"max_bytes": MAX_SVC_UPLOAD_BYTES},
            )
        except Exception as e:
            logger.error("SVC error: %s", e)
            return error_response(code="svc_error", message="SVC conversion failed", status_code=500)

    return router
