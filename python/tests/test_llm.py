"""Basic tests for LLMClient wiring.

These are lightweight connectivity/contract tests that
exercise the client construction without depending on a
real remote LLM service.
"""

import importlib

import httpx

pytest = importlib.import_module("pytest")


def test_extract_model_ids_accepts_common_model_list_shapes():
    extract_model_ids = importlib.import_module("modules.llm.client").extract_model_ids

    assert extract_model_ids({"data": [{"id": "gpt-a"}, {"id": "gpt-a"}, {"name": "gpt-b"}]}) == ["gpt-a", "gpt-b"]
    assert extract_model_ids({"models": ["gpt-c", {"id": "gpt-d"}]}) == ["gpt-c", "gpt-d"]


def test_normalize_openai_base_url_removes_final_endpoint_paths():
    normalize_openai_base_url = importlib.import_module("modules.llm.client").normalize_openai_base_url

    assert normalize_openai_base_url("https://api.example/v1/chat/completions") == "https://api.example/v1"
    assert normalize_openai_base_url("https://api.example/v1/models/") == "https://api.example/v1"


def test_llm_client_normalizes_copied_chat_completion_url():
    LLMClient = importlib.import_module("modules.llm").LLMClient

    client = LLMClient("https://api.example/v1/chat/completions", "", "model", 1)

    assert client.base_url == "https://api.example/v1"


def test_ollama_provider_uses_local_openai_compatible_defaults():
    providers = importlib.import_module("modules.llm.providers")

    assert providers.normalize_llm_provider("ollama") == "ollama"
    assert providers.infer_llm_provider("http://localhost:11434/v1/models") == "ollama"
    assert providers.normalize_llm_base_url("", "ollama") == "http://localhost:11434/v1"
    assert providers.llm_models_url("", "ollama") == "http://localhost:11434/v1/models"
    assert providers.llm_chat_url("", "ollama") == "http://localhost:11434/v1/chat/completions"


def test_lmstudio_provider_uses_local_openai_compatible_defaults():
    providers = importlib.import_module("modules.llm.providers")

    assert providers.normalize_llm_provider("lm-studio") == "lmstudio"
    assert providers.normalize_llm_provider("lm_studio") == "lmstudio"
    assert providers.infer_llm_provider("http://localhost:1234/v1/models") == "lmstudio"
    assert providers.normalize_llm_base_url("", "lmstudio") == "http://localhost:1234/v1"
    assert providers.llm_models_url("", "lmstudio") == "http://localhost:1234/v1/models"
    assert providers.llm_chat_url("", "lmstudio") == "http://localhost:1234/v1/chat/completions"


def test_provider_protocols_keep_native_gemini_separate_from_compatibility_gateways():
    providers = importlib.import_module("modules.llm.providers")

    assert providers.llm_protocol("gemini") == "gemini-generate-content"
    assert ":generateContent" in providers.llm_request_url("", "gemini", model="gemini-2.5-flash")
    assert providers.llm_protocol("gemini", "https://gateway.example/v1/openai") == "openai-chat-completions"


def test_model_registry_exposes_numeric_limits_without_guessing_unknown_models():
    capabilities = importlib.import_module("modules.llm.capabilities")

    assert capabilities.get_model_limits("deepseek", "deepseek-v4-flash") == {
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 384_000,
    }
    assert capabilities.get_model_limits("custom", "local-model") == {}


def test_llm_budget_clamp_uses_registered_limit_only():
    client_module = importlib.import_module("modules.llm.client")
    config = importlib.import_module("modules.core.config").config
    original_provider = config.llm.provider
    original_model = config.llm.model
    try:
        config.llm.provider = "deepseek"
        config.llm.model = "deepseek-v4-flash"
        assert client_module._effective_model_budget(
            "deepseek-v4-flash", 1_100_000, 8_192, "context_window_tokens", log_clamp=False
        ) == 1_000_000
        assert client_module._effective_model_budget(
            "local-model", 1_100_000, 8_192, "context_window_tokens", log_clamp=False
        ) == 1_100_000
    finally:
        config.llm.provider = original_provider
        config.llm.model = original_model


def test_gemini_payload_uses_native_contents_and_generation_config():
    client_module = importlib.import_module("modules.llm.client")

    payload = client_module._messages_to_gemini_payload({
        "model": "gemini-2.5-flash",
        "max_tokens": 64,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "hello"},
        ],
    })

    assert payload["systemInstruction"]["parts"][0]["text"] == "You are concise."
    assert payload["contents"][0] == {"role": "user", "parts": [{"text": "hello"}]}
    assert payload["generationConfig"]["maxOutputTokens"] == 64
    assert payload["generationConfig"]["temperature"] == 0.2


def test_lmstudio_provider_aliases_validate_in_runtime_settings_patch():
    validate_runtime_patch = importlib.import_module("modules.system.settings_schema").validate_runtime_patch

    patch = validate_runtime_patch({"llm": {"provider": "lm-studio"}})

    assert patch.llm is not None
    assert patch.llm.provider == "lmstudio"


@pytest.mark.asyncio
async def test_llm_client_connect_disconnect():
    config = importlib.import_module("modules.core.config").config
    LLMClient = importlib.import_module("modules.llm").LLMClient
    client = LLMClient(
        config.llm.base_url,
        config.llm.api_key,
        config.llm.model,
        config.llm.timeout,
    )
    await client.connect()
    # 只检查内部 HTTP 客户端是否被创建
    assert getattr(client, "_http", None) is not None
    await client.disconnect()


@pytest.mark.asyncio
async def test_llm_client_stream_chat_signature():
    """Ensure stream_chat can be invoked with expected signature.

    使用假 WebSocket/generation_mgr/messages 验证函数签名不报错，
    不断言远端行为（避免依赖真实 OpenAI 服务）。
    """

    config = importlib.import_module("modules.core.config").config
    GenerationManager = importlib.import_module("modules.core").GenerationManager
    LLMClient = importlib.import_module("modules.llm").LLMClient

    class DummyWS:
        async def send_text(self, *_args, **_kwargs):  # pragma: no cover - trivial
            return None

        async def send_json(self, *_args, **_kwargs):  # pragma: no cover - trivial
            return None

    client = LLMClient(
        config.llm.base_url,
        config.llm.api_key,
        config.llm.model,
        config.llm.timeout,
    )
    await client.connect()
    generation_mgr = GenerationManager()
    generation = generation_mgr.start("test-llm-session")
    try:
        await client.stream_chat(DummyWS(), generation, generation_mgr, [])
    except Exception:
        # 这里只关心调用路径存在，不要求远端成功
        pass
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_complete_chat_applies_request_options():
    LLMClient = importlib.import_module("modules.llm").LLMClient

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class DummyHTTP:
        def __init__(self):
            self.body = None

        async def post(self, _url, json=None, headers=None):
            self.body = json
            return DummyResponse()

    http = DummyHTTP()
    client = LLMClient("http://llm.test/v1", "", "default-model", 1)
    client._http = http

    await client.complete_chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-test",
        temperature=0.2,
        top_p=0.8,
        top_k=42,
        min_p=0.04,
        frequency_penalty=0.3,
        presence_penalty=0.1,
        repetition_penalty=1.08,
        reasoning_effort="high",
        max_output_tokens=256,
    )

    assert http.body["model"] == "gpt-test"
    assert http.body["temperature"] == 0.2
    assert http.body["top_p"] == 0.8
    assert http.body["top_k"] == 42
    assert http.body["min_p"] == 0.04
    assert http.body["frequency_penalty"] == 0.3
    assert http.body["presence_penalty"] == 0.1
    assert http.body["repetition_penalty"] == 1.08
    assert http.body["reasoning_effort"] == "high"
    assert http.body["max_tokens"] == 256


@pytest.mark.asyncio
async def test_complete_chat_falls_back_when_tools_are_rejected():
    LLMClient = importlib.import_module("modules.llm").LLMClient

    class RejectToolsResponse:
        def raise_for_status(self):
            request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
            response = httpx.Response(
                400,
                request=request,
                content=b'{"error":"tools unsupported"}',
            )
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    class OkResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "fallback ok"}}]}

    class DummyHTTP:
        def __init__(self):
            self.posts = []

        async def post(self, _url, json=None, headers=None):
            self.posts.append(json)
            if len(self.posts) == 1:
                return RejectToolsResponse()
            return OkResponse()

    http = DummyHTTP()
    client = LLMClient("http://llm.test/v1", "", "default-model", 1)
    client._http = http
    tools = [{
        "type": "function",
        "function": {
            "name": "demo_tool",
            "description": "Demo",
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    first = await client.complete_chat([{"role": "user", "content": "hello"}], tools=tools)
    second = await client.complete_chat([{"role": "user", "content": "again"}], tools=tools)

    assert first["reply"] == "fallback ok"
    assert second["reply"] == "fallback ok"
    assert "tools" in http.posts[0]
    assert "tools" not in http.posts[1]
    assert "tools" not in http.posts[2]
    assert client._tool_calls_supported is False


@pytest.mark.asyncio
async def test_complete_chat_retries_when_reasoning_consumes_small_token_budget():
    LLMClient = importlib.import_module("modules.llm").LLMClient

    class ReasoningOnlyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{
                    "finish_reason": "length",
                    "message": {
                        "content": "",
                        "reasoning_content": "Thinking used the tiny token budget.",
                    },
                }]
            }

    class OkResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class DummyHTTP:
        def __init__(self):
            self.posts = []

        async def post(self, _url, json=None, headers=None):
            self.posts.append(json)
            if len(self.posts) == 1:
                return ReasoningOnlyResponse()
            return OkResponse()

    http = DummyHTTP()
    client = LLMClient("http://llm.test/v1", "", "default-model", 1)
    client._http = http

    result = await client.complete_chat(
        [{"role": "user", "content": "reply exactly OK"}],
        max_output_tokens=16,
    )

    assert result["reply"] == "OK"
    assert http.posts[0]["max_tokens"] == 16
    assert http.posts[1]["max_tokens"] == 256


@pytest.mark.asyncio
async def test_llm_test_connection_checks_chat_after_models_success():
    LLMClient = importlib.import_module("modules.llm").LLMClient

    class OkResponse:
        def raise_for_status(self):
            return None

    class DummyHTTP:
        def __init__(self):
            self.get_count = 0
            self.post_count = 0

        async def get(self, _url, headers=None):
            self.get_count += 1
            return OkResponse()

        async def post(self, _url, json=None, headers=None):
            self.post_count += 1
            return OkResponse()

    http = DummyHTTP()
    client = LLMClient("http://llm.test/v1", "", "default-model", 1)
    client._http = http

    result = await client.test_connection()

    assert result == {"ok": True, "message": "LLM connection OK (provider chat endpoint)"}
    assert http.get_count == 1
    assert http.post_count == 1


@pytest.mark.asyncio
async def test_llm_test_connection_reports_chat_error_after_models_success():
    LLMClient = importlib.import_module("modules.llm").LLMClient

    class ModelsOkResponse:
        def raise_for_status(self):
            return None

    class ChatRejectedResponse:
        def raise_for_status(self):
            request = httpx.Request("POST", "http://llm.test/v1/chat/completions")
            response = httpx.Response(
                400,
                request=request,
                content=b'{"error":"bad model"}',
            )
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    class DummyHTTP:
        async def get(self, _url, headers=None):
            return ModelsOkResponse()

        async def post(self, _url, json=None, headers=None):
            return ChatRejectedResponse()

    client = LLMClient("http://llm.test/v1", "", "bad-model", 1)
    client._http = DummyHTTP()

    result = await client.test_connection()

    assert result["ok"] is False
    assert result["message"].startswith("LLM API 400:")
    assert "bad model" in result["message"]
