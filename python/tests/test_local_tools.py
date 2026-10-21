from __future__ import annotations

import pytest

from modules.tools.local_tools import LocalToolError, dispatch_tool


def test_dispatch_tool_rejects_non_integer_search_limit() -> None:
    with pytest.raises(LocalToolError, match="limit must be an integer"):
        dispatch_tool("web_search", {"query": "yuizaki", "limit": "many"})

