import importlib

pytest = importlib.import_module("pytest")


@pytest.mark.asyncio
async def test_tool_loop_sends_openai_safe_names_and_executes_registry_name():
    tool_loop = importlib.import_module("modules.agent.tool_loop")
    tool_registry_module = importlib.import_module("modules.agent.tool_registry")
    tool_result_module = importlib.import_module("modules.agent.tool_result")

    ToolDefinition = tool_registry_module.ToolDefinition
    ToolRegistry = tool_registry_module.ToolRegistry
    ToolResultEnvelope = tool_result_module.ToolResultEnvelope

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="time.now",
        description="Get current time",
        source="builtin",
        parameters={"type": "object", "properties": {}},
        handler=lambda _args: ToolResultEnvelope(
            success=True,
            content="2026-07-04T19:30:00",
            source="builtin",
            tool_name="time.now",
        ),
    ))

    class FakeLLM:
        def __init__(self):
            self.calls = []

        async def complete_chat(self, messages, **kwargs):
            self.calls.append({"messages": messages, "kwargs": kwargs})
            tools = kwargs.get("tools") or []
            assert tools[0]["function"]["name"] == "time_now"
            if len(self.calls) == 1:
                return {
                    "reply": "",
                    "reasoning_content": "Need the clock result before answering.",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "time_now", "arguments": "{}"},
                    }],
                    "pet_control": None,
                }
            return {"reply": "工具结果已读取。", "tool_calls": [], "pet_control": None}

    class FakeExecutor:
        def __init__(self):
            self.calls = []

        async def execute(self, tool_name, args, **_kwargs):
            self.calls.append((tool_name, args))
            return ToolResultEnvelope(
                success=True,
                content="2026-07-04T19:30:00",
                source="builtin",
                tool_name=tool_name,
            )

    llm = FakeLLM()
    executor = FakeExecutor()

    result = await tool_loop.run_tool_loop(
        llm,
        [{"role": "user", "content": "现在几点"}],
        tool_registry=registry,
        tool_executor=executor,
        include_mcp_tools=False,
        include_web_search_tools=False,
    )

    assert result["reply"] == "工具结果已读取。"
    assert executor.calls == [("time.now", {})]
    assistant_tool_message = llm.calls[1]["messages"][-2]
    assert assistant_tool_message["role"] == "assistant"
    assert assistant_tool_message["reasoning_content"] == "Need the clock result before answering."


@pytest.mark.asyncio
async def test_tool_loop_limits_mcp_tools_to_workspace_server_preset():
    tool_loop = importlib.import_module("modules.agent.tool_loop")
    tool_registry_module = importlib.import_module("modules.agent.tool_registry")
    tool_result_module = importlib.import_module("modules.agent.tool_result")

    ToolDefinition = tool_registry_module.ToolDefinition
    ToolRegistry = tool_registry_module.ToolRegistry
    ToolResultEnvelope = tool_result_module.ToolResultEnvelope
    registry = ToolRegistry()

    def register(name, source, tags=None, scopes=None):
        registry.register(ToolDefinition(
            name=name,
            description=name,
            source=source,
            parameters={"type": "object", "properties": {}},
            handler=lambda _args: ToolResultEnvelope(
                success=True,
                content="ok",
                source=source,
                tool_name=name,
            ),
            tags=tags,
            scopes=scopes,
        ))

    register("time.now", "builtin")
    register("calendar.list", "mcp", tags=["mcp-server:calendar"])
    register("browser.open_page", "mcp", scopes=["mcp:playwright", "browser:open_page"])

    class FakeLLM:
        def __init__(self):
            self.tools = []

        async def complete_chat(self, _messages, **kwargs):
            self.tools = kwargs.get("tools") or []
            return {"reply": "done", "tool_calls": [], "pet_control": None}

    llm = FakeLLM()
    await tool_loop.run_tool_loop(
        llm,
        [{"role": "user", "content": "read calendar"}],
        tool_registry=registry,
        tool_executor=object(),
        allowed_mcp_server_names=["calendar"],
    )

    names = {item["function"]["name"] for item in llm.tools}
    assert names == {"time_now", "calendar_list"}
