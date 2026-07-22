from __future__ import annotations

from typing import Any

LLM_PROVIDER_VALUES = ("deepseek", "qwen", "gemini", "chatgpt", "claude", "grok", "ollama", "lmstudio", "custom")
OPENAI_COMPATIBLE_PROVIDERS = {"deepseek", "qwen", "gemini", "chatgpt", "grok", "ollama", "lmstudio", "custom"}

DEFAULT_PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # Gemini uses its native generateContent protocol by default. Users can
    # still point it at an OpenAI-compatible gateway explicitly.
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "chatgpt": "https://api.openai.com/v1",
    "claude": "https://api.anthropic.com/v1",
    "grok": "https://api.x.ai/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "custom": "",
}


def infer_llm_provider(base_url: str) -> str:
    normalized = (base_url or "").strip().lower()
    if not normalized:
        return "custom"
    if "deepseek.com" in normalized:
        return "deepseek"
    if "dashscope.aliyuncs.com" in normalized or "dashscope-intl.aliyuncs.com" in normalized:
        return "qwen"
    if "generativelanguage.googleapis.com" in normalized:
        return "gemini"
    if "api.openai.com" in normalized:
        return "chatgpt"
    if "api.anthropic.com" in normalized or "anthropic.com" in normalized:
        return "claude"
    if "api.x.ai" in normalized or "x.ai" in normalized:
        return "grok"
    if "localhost:11434" in normalized or "127.0.0.1:11434" in normalized or "[::1]:11434" in normalized:
        return "ollama"
    if "localhost:1234" in normalized or "127.0.0.1:1234" in normalized or "[::1]:1234" in normalized:
        return "lmstudio"
    return "custom"


def normalize_llm_provider(provider: Any, base_url: str = "") -> str:
    value = str(provider or "").strip().lower()
    aliases = {
        "openai": "chatgpt",
        "chat-gpt": "chatgpt",
        "openai-compatible": "custom",
        "azure": "custom",
        "azure-compatible": "custom",
        "ollama": "ollama",
        "anthropic": "claude",
        "xai": "grok",
        "x-ai": "grok",
        "dashscope": "qwen",
        "lm-studio": "lmstudio",
        "lm_studio": "lmstudio",
    }
    value = aliases.get(value, value)
    if value in LLM_PROVIDER_VALUES:
        return value
    return infer_llm_provider(base_url)


def normalize_llm_base_url(base_url: str, provider: str = "custom") -> str:
    endpoint = (base_url or "").strip().rstrip("/")
    provider = normalize_llm_provider(provider, endpoint)
    suffixes = ("/messages", "/chat/completions", "/models")
    for suffix in suffixes:
        if endpoint.lower().endswith(suffix):
            endpoint = endpoint[: -len(suffix)].rstrip("/")
    if not endpoint:
        return DEFAULT_PROVIDER_BASE_URLS.get(provider, "")
    return endpoint


def llm_models_url(base_url: str, provider: str = "custom") -> str:
    return f"{normalize_llm_base_url(base_url, provider)}/models"


def llm_chat_url(base_url: str, provider: str = "custom") -> str:
    normalized_provider = normalize_llm_provider(provider, base_url)
    if normalized_provider == "claude":
        return f"{normalize_llm_base_url(base_url, normalized_provider)}/messages"
    return f"{normalize_llm_base_url(base_url, normalized_provider)}/chat/completions"


def llm_protocol(provider: str, base_url: str = "") -> str:
    """Return the wire protocol selected for a configured provider."""
    normalized = normalize_llm_provider(provider, base_url)
    endpoint = (base_url or "").lower()
    if normalized == "claude":
        return "anthropic-messages"
    if normalized == "gemini" and "/openai" not in endpoint:
        return "gemini-generate-content"
    return "openai-chat-completions"


def llm_request_url(
    base_url: str,
    provider: str = "custom",
    *,
    model: str = "",
    stream: bool = False,
) -> str:
    """Build the provider-native generation URL without leaking credentials."""
    normalized = normalize_llm_provider(provider, base_url)
    protocol = llm_protocol(normalized, base_url)
    endpoint = normalize_llm_base_url(base_url, normalized)
    if protocol == "gemini-generate-content":
        model = str(model or "").removeprefix("models/")
        action = "streamGenerateContent" if stream else "generateContent"
        return f"{endpoint}/models/{model}:{action}"
    return llm_chat_url(endpoint, normalized)


def build_llm_auth_headers(api_key: str, provider: str = "custom") -> dict[str, str]:
    normalized_provider = normalize_llm_provider(provider)
    if normalized_provider == "gemini":
        return {"x-goog-api-key": api_key} if api_key else {}
    if normalized_provider == "claude":
        headers = {"anthropic-version": "2023-06-01"}
        if api_key:
            headers["x-api-key"] = api_key
        return headers
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def is_claude_provider(provider: str) -> bool:
    return normalize_llm_provider(provider) == "claude"
