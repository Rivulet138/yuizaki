from __future__ import annotations
from typing import Any
from socket_handlers.tool import build_tool_call_handler, build_tool_recheck_handler
from socket_events import ToolEvents

def register(server: Any) -> None:
    sio = server.sio
    on_call = build_tool_call_handler(
        sio=sio, tool_executor=server.tool_executor, tool_registry=server.tool_registry,
        trace_store=server.trace_store, plugin_manager=server.plugin_manager,
        active_workspace_id=server._active_workspace_id,
        bind_ctx_runtime=lambda ctx: server._bind_ctx_runtime(ctx, include_visual=False),
        tool_cancellation_signals=server._tool_cancellation_signals,
        permission_request_tool_map=server._permission_request_tool_map,
        permission_request_scope_map=server._permission_request_scope_map,
        permission_request_sid_map=server._permission_request_sid_map,
        logger=server.logger,
    )
    sio.on(ToolEvents.CALL, handler=on_call)
    on_recheck = build_tool_recheck_handler(
        sio=sio, tool_executor=server.tool_executor, tool_registry=server.tool_registry,
        trace_store=server.trace_store, plugin_manager=server.plugin_manager,
        active_workspace_id=server._active_workspace_id,
        bind_ctx_runtime=lambda ctx: server._bind_ctx_runtime(ctx, include_visual=False), logger=server.logger,
    )
    sio.on(ToolEvents.RECHECK, handler=on_recheck)
