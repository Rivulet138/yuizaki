"""Socket.IO text-generation handler.

The legacy server remains the runtime owner.  This module owns the LLM event
boundary and receives the small parsing/projection helpers that are still
shared with the other transports.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from modules.agent.context import AgentRequestContext
from modules.agent.response_profile import (
    resolve_reasoning_effort,
    resolve_thinking_mode,
)
from socket_events import (
    AgentEvents,
    LLMDeltaData,
    LLMEvents,
    LLMFinalData,
    LLMRequestData,
    PetEvents,
    SystemEvents,
)
from starlette.concurrency import run_in_threadpool

JsonDict = dict[str, object]
Handler = Callable[[str, JsonDict], Awaitable[None]]


@dataclass(frozen=True)
class LLMRequestSupport:
    """Pure request parsing and event projection shared with the server facade."""

    request_identity: Callable[..., JsonDict]
    as_text: Callable[..., str]
    as_int: Callable[..., int]
    as_json_dict: Callable[..., JsonDict]
    as_messages: Callable[..., list[dict[str, str]]]
    optional_float: Callable[..., float | None]
    optional_bool: Callable[..., bool | None]
    request_option: Callable[..., object]
    request_tts_enabled: Callable[..., bool]
    request_prompt_profile: Callable[..., JsonDict | None]
    request_response_mode: Callable[..., Any]
    prompt_mode: Callable[..., str | None]
    event_payload: Callable[..., JsonDict]
    generation_identity: Callable[..., JsonDict]
    agent_result_payload: Callable[..., JsonDict]


def build_llm_request_handler(
    *,
    server: Any,
    support: LLMRequestSupport,
    logger: logging.Logger | None = None,
) -> Handler:
    """Build the text-generation handler against the live server runtime."""

    log = logger or logging.getLogger("socket-server.llm")

    async def on_llm_request(sid: str, data: JsonDict) -> None:
        log.info("[SIO] llm:request from %s", sid)
        request_identity = support.request_identity(
            data,
            support.as_text(data.get("session_id"), sid),
        )

        llm_client = server.llm_client
        if llm_client is None:
            await server.sio.emit(SystemEvents.ERROR, {
                "code": "LLM_NOT_READY",
                "message": "LLM client not initialized",
                **request_identity,
            }, to=sid)
            return

        generation_mgr = server.generation_mgr
        if generation_mgr is None:
            await server.sio.emit(SystemEvents.ERROR, {
                "code": "GEN_MGR_NOT_READY",
                "message": "Generation manager not initialized",
                **request_identity,
            }, to=sid)
            return

        request_temperature = support.optional_float(support.request_option(data, "temperature"))
        request_top_p = support.optional_float(support.request_option(data, "top_p"))
        top_k_option = support.request_option(data, "top_k")
        request_top_k = support.as_int(top_k_option, 0) if top_k_option is not None else None
        request_min_p = support.optional_float(support.request_option(data, "min_p"))
        request_frequency_penalty = support.optional_float(support.request_option(data, "frequency_penalty"))
        request_presence_penalty = support.optional_float(support.request_option(data, "presence_penalty"))
        request_repetition_penalty = support.optional_float(support.request_option(data, "repetition_penalty"))
        payload = LLMRequestData(
            messages=support.as_messages(data.get("messages")),
            session_id=support.as_text(data.get("session_id")),
            temperature=request_temperature,
            top_p=request_top_p,
            top_k=request_top_k,
            min_p=request_min_p,
            frequency_penalty=request_frequency_penalty,
            presence_penalty=request_presence_penalty,
            repetition_penalty=request_repetition_penalty,
            max_tokens=support.as_int(support.request_option(data, "max_tokens"), 8192),
        )
        pet_control_context = support.as_json_dict(data.get("pet_control_context")) or None
        requested_workspace_id = support.as_text(data.get("workspace_id")) or None
        workspace_id, workspace_allowed = server._resolve_socket_workspace_id(requested_workspace_id)
        if not workspace_allowed:
            await server.sio.emit(SystemEvents.ERROR, {
                "code": "WORKSPACE_MISMATCH",
                "message": "Socket request workspace does not match the active workspace",
                **request_identity,
            }, to=sid)
            return
        request_id = support.as_text(data.get("request_id")).strip() or f"agent_{uuid.uuid4().hex[:12]}"
        model = support.as_text(support.request_option(data, "model")) or None
        reasoning_effort = support.as_text(support.request_option(data, "reasoning_effort")) or None
        mcp_enabled = support.optional_bool(support.request_option(data, "mcp_enabled"))
        web_search_enabled = support.optional_bool(support.request_option(data, "web_search_enabled"))
        tts_enabled = support.request_tts_enabled(data)
        prompt_profile = support.request_prompt_profile(data)
        response_mode = support.request_response_mode(data)
        thinking_mode = resolve_thinking_mode(
            reasoning_effort,
            response_mode=response_mode,
            prompt_mode=support.prompt_mode(prompt_profile),
            mcp_enabled=mcp_enabled,
            web_search_enabled=web_search_enabled,
            messages=payload.messages,
            model_hint=model or getattr(llm_client, "model", None),
            provider_hint=getattr(llm_client, "provider", None),
        )
        reasoning_effort = resolve_reasoning_effort(
            reasoning_effort,
            response_mode=response_mode,
            prompt_mode=support.prompt_mode(prompt_profile),
            mcp_enabled=mcp_enabled,
            web_search_enabled=web_search_enabled,
            messages=payload.messages,
            model_hint=model or getattr(llm_client, "model", None),
            provider_hint=getattr(llm_client, "provider", None),
        )

        session_id = payload.session_id or sid
        generation_id = support.as_text(data.get("generation_id")).strip() or None
        turn_id = support.as_text(data.get("turn_id")).strip() or None
        interruption_epoch = max(0, support.as_int(data.get("interruption_epoch"), 0))
        envelope_version = max(1, support.as_int(data.get("version"), 1))
        gen = generation_mgr.start(
            session_id,
            generation_id=generation_id,
            turn_id=turn_id,
            request_id=request_id,
            interruption_epoch=interruption_epoch,
            envelope_version=envelope_version,
            conversation_id=support.as_text(data.get("conversation_id")),
            operation_id=support.as_text(data.get("operation_id")),
            run_id=support.as_text(data.get("run_id")),
            step_index=max(0, support.as_int(data.get("step_index"), 0)),
        )
        server._bind_generation_to_sid(sid, gen)
        llm_sequence = 0
        terminal_requested = False
        terminal_replayed = False
        outer_server = server

        class _SocketIOWSAdapter:
            def __init__(self, client_sid: str) -> None:
                self._sid = client_sid
                self._turn_context: AgentRequestContext | None = None

            def bind_turn_context(self, ctx: AgentRequestContext) -> None:
                self._turn_context = ctx

            async def send_json(self, msg: JsonDict) -> None:
                nonlocal llm_sequence, terminal_requested, terminal_replayed
                if not outer_server._generation_is_current(gen):
                    return
                msg_type = msg.get("type")
                if msg_type == "token":
                    token = support.as_text(msg.get("content"))
                    await outer_server.sio.emit(LLMEvents.DELTA, support.event_payload(LLMDeltaData(
                        token=token,
                        index=llm_sequence,
                        session_id=session_id,
                        generation_id=gen.generation_id,
                        turn_id=gen.turn_id,
                        request_id=gen.request_id,
                        interruption_epoch=gen.interruption_epoch,
                        version=gen.envelope_version,
                        sequence=llm_sequence,
                    )), to=self._sid)
                    llm_sequence += 1
                elif msg_type == "done":
                    terminal_requested = True
                    terminal_replayed = bool(msg.get("replayed"))
                    if hasattr(gen, "mark"):
                        gen.mark("llm_completed")
                elif msg_type == "pet_control":
                    avatar_command = outer_server._build_avatar_command(
                        msg.get("pet_control", {}),
                        session_id=session_id,
                        request_id=request_id,
                        capability_revision=support.as_text((pet_control_context or {}).get("capabilityRevision")) or None,
                    )
                    await outer_server.sio.emit(PetEvents.CONTROL, {
                        "session_id": session_id,
                        "generation_id": gen.generation_id,
                        "turn_id": gen.turn_id,
                        "request_id": gen.request_id,
                        "interruption_epoch": gen.interruption_epoch,
                        "version": gen.envelope_version,
                        "pet_control": msg.get("pet_control", {}),
                        **({"avatar_command": avatar_command} if avatar_command else {}),
                    }, to=self._sid)
                elif msg_type == "error":
                    await outer_server.sio.emit(SystemEvents.ERROR, {
                        "code": "LLM_ERROR",
                        "message": msg.get("error", "LLM error"),
                        "session_id": session_id,
                        **support.generation_identity(gen),
                    }, to=self._sid)
                else:
                    log.debug("[SIO] unhandled LLM message: %s", msg_type)

        ws_adapter = _SocketIOWSAdapter(sid)

        async def _run_llm_and_tts() -> None:
            ctx = AgentRequestContext(
                sid=sid,
                session_id=session_id,
                request_id=request_id,
                turn_id=gen.turn_id,
                generation_id=gen.generation_id,
                interruption_epoch=gen.interruption_epoch,
                messages=server._with_latest_visual_context(sid, payload.messages),
                temperature=payload.temperature,
                top_p=payload.top_p,
                top_k=payload.top_k,
                min_p=payload.min_p,
                frequency_penalty=payload.frequency_penalty,
                presence_penalty=payload.presence_penalty,
                repetition_penalty=payload.repetition_penalty,
                max_tokens=payload.max_tokens,
                model=model,
                reasoning_effort=reasoning_effort,
                thinking_mode=thinking_mode,
                response_mode=response_mode,
                mcp_enabled=mcp_enabled,
                web_search_enabled=web_search_enabled,
                prompt_profile=prompt_profile,
                pet_control_context=pet_control_context,
                workspace_id=workspace_id,
                llm_client=llm_client,
                generation_mgr=generation_mgr,
                tool_registry=server.tool_registry,
                tool_executor=server.tool_executor,
                step_executor=server.step_executor,
                scheduler=server.scheduler,
                trace_store=server.trace_store,
                plugin_manager=server.plugin_manager,
                permission_scope=f"socket:{sid}",
            )
            server._bind_ctx_runtime(ctx)
            ws_adapter.bind_turn_context(ctx)
            turn_service = server._semantic_turn_service()
            commit = None
            if turn_service is None:
                result_obj = await server.agent_pipeline.run_streaming(ctx, ws_adapter, gen)
            else:
                commit = await turn_service.execute_streaming_context("socket", ctx, ws_adapter, gen)
                result_obj = commit.result
            if not server._generation_is_current(gen):
                return
            if turn_service is not None:
                message_ids = await run_in_threadpool(server._resolve_turn_message_ids, ctx)
            elif terminal_replayed:
                message_ids = {"user_message_id": None, "assistant_message_id": None}
            else:
                message_ids = await run_in_threadpool(
                    server._persist_chat_exchange,
                    session_id=session_id,
                    workspace_id=workspace_id,
                    messages=payload.messages,
                    assistant_text=result_obj.reply,
                    model=model,
                )
            persisted_assistant_message_id = message_ids["assistant_message_id"]
            await run_in_threadpool(
                server._persist_message_metadata,
                persisted_assistant_message_id,
                result_obj.action_envelope,
            )
            if not server._generation_is_current(gen):
                return
            await server.sio.emit(
                AgentEvents.RESULT,
                support.agent_result_payload(
                    result_obj.action_envelope or {},
                    session_id,
                    {**support.generation_identity(gen), **server._turn_commit_fields(commit, result_obj)},
                ),
                to=sid,
            )
            if not server._generation_is_current(gen):
                return
            final_payload = support.event_payload(LLMFinalData(
                text=result_obj.reply,
                session_id=session_id,
                user_message_id=message_ids["user_message_id"],
                assistant_message_id=message_ids["assistant_message_id"],
                generation_id=gen.generation_id,
                turn_id=gen.turn_id,
                request_id=gen.request_id,
                interruption_epoch=gen.interruption_epoch,
                version=gen.envelope_version,
                sequence=llm_sequence,
                tts_expected=tts_enabled and server.tts_client is not None,
            ))
            final_payload.update(server._turn_commit_fields(commit, result_obj))
            await server.sio.emit(LLMEvents.FINAL, final_payload, to=sid)
            if hasattr(gen, "latency_snapshot"):
                await server._emit_latency(sid, gen.latency_snapshot())

            if terminal_requested and tts_enabled and server.tts_client and server._generation_is_current(gen):
                await server._run_tts_for_generation(session_id, sid)

        gen.llm_task = asyncio.create_task(
            _run_llm_and_tts(),
            name=f"llm-sio-{gen.generation_id}",
        )
        server._attach_chat_task_error_handler(
            gen.llm_task,
            sid=sid,
            session_id=session_id,
            generation=gen,
        )

    return on_llm_request


def register_llm_handler(
    *,
    sio: Any,
    server: Any,
    support: LLMRequestSupport,
    logger: logging.Logger | None = None,
) -> Handler:
    handler = build_llm_request_handler(server=server, support=support, logger=logger)
    sio.on(LLMEvents.REQUEST, handler=handler)
    return handler


__all__ = ["LLMRequestSupport", "build_llm_request_handler", "register_llm_handler"]
