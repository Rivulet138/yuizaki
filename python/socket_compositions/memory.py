from __future__ import annotations
from typing import Any
from socket_handlers.memory import build_memory_query_handler
from socket_events import MemoryEvents

def register(server: Any) -> None:
    handler = build_memory_query_handler(
        sio=server.sio,
        retrieval_pipeline_provider=lambda: server.agent_pipeline.retrieval_pipeline,
        workspace_resolver=server._resolve_socket_workspace_id,
        default_layers=list(server.default_rag_layers), logger=server.logger,
    )
    server.sio.on(MemoryEvents.QUERY, handler=handler)
