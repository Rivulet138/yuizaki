from __future__ import annotations
from typing import Any
from socket_handlers.system import register_system_handlers
from socket_handlers.interrupt import register_interrupt_handler

def register(server: Any) -> None:
    register_interrupt_handler(
        sio=server.sio, generation_manager_provider=lambda: server.generation_mgr,
        advance_interruption_epoch=server._advance_interruption_epoch,
        cancel_visual_turn=server._cancel_visual_turn_for_interrupt,
        cancel_direct_tool_calls=server._cancel_direct_tool_calls,
        record_interrupt=server.experience_metrics.record_interrupt, logger=server.logger,
    )
    register_system_handlers(
        sio=server.sio, generation_manager_provider=lambda: server.generation_mgr,
        experience_metrics=server.experience_metrics, emit_latency=server._emit_latency,
        permission_request_sid_map=server._permission_request_sid_map,
        permission_request_tool_map=server._permission_request_tool_map,
        permission_request_scope_map=server._permission_request_scope_map,
        tool_executor=server.tool_executor, logger=server.logger,
    )
