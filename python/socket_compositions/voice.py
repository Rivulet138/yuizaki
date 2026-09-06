from __future__ import annotations
from typing import Any
from socket_handlers.voice import build_svc_convert_handler
from socket_events import SVCEvents

def register(server: Any) -> None:
    handler = build_svc_convert_handler(sio=server.sio, svc_client_provider=lambda: server.svc_client, logger=server.logger)
    server.sio.on(SVCEvents.CONVERT, handler=handler)
