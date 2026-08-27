"""Narrow Socket.IO domain handlers kept behind the legacy server façade."""

from .tool import build_tool_call_handler

__all__ = ["build_tool_call_handler"]
