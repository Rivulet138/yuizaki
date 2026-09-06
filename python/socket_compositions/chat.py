from __future__ import annotations
from typing import Any
from socket_handlers.llm import LLMRequestSupport, register_llm_handler

def register(server: Any, support: LLMRequestSupport) -> None:
    register_llm_handler(sio=server.sio, server=server, support=support, logger=server.logger)
